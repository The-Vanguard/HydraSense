"""tests/test_redesign_backend.py -- KPI summary, region peak rainfall and per-hazard history fields."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import village_cycle as vc  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import village as vapi  # noqa: E402


def test_village_summary_counts_unscored_separately(monkeypatch, tmp_path):
    for code in ("aa-x", "bb-y"):
        (tmp_path / f"{code}.gpkg").write_text("")
    monkeypatch.setattr(vapi, "GPKG_DIR", tmp_path)
    fake = {
        "aa-x": dict(villages=5, scored=3, tier_counts={"Red": 1, "Orange": 0, "Yellow": 1, "Green": 1},
                     top_village=dict(village_id="v1", name="A", alert_tier="Red", alert_value=80.0)),
        "bb-y": dict(villages=2, scored=2, tier_counts={"Red": 0, "Orange": 1, "Yellow": 0, "Green": 1},
                     top_village=dict(village_id="v9", name="B", alert_tier="Orange", alert_value=60.0)),
    }
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(vc, "SUMMARY", {k: dict(v, at=now) for k, v in fake.items()})
    d = TestClient(app).get("/village/summary").json()
    assert d["tier_counts"] == {"Red": 1, "Orange": 1, "Yellow": 1, "Green": 2}
    assert d["villages"] == 7 and d["scored_villages"] == 5 and d["unscored_villages"] == 2
    assert d["top_village"]["name"] == "A" and d["top_village"]["region_code"] == "aa-x"
    one = TestClient(app).get("/village/summary", params={"region": "bb-y"}).json()
    assert one["tier_counts"]["Orange"] == 1 and one["villages"] == 2


def test_history_model_has_optional_hazard_fields():
    from backend.models import RiskHistoryEntry
    e = RiskHistoryEntry(timestamp="t", risk_score=1.0, tier="Green")
    assert e.index_flood is None and e.index_landslide is None and e.rainfall_24h is None


def test_replay_without_rainfall_returns_no_steps_and_a_reason(monkeypatch):
    from backend.routers import events
    monkeypatch.setattr(events, "get_event_rainfall_window",
                        lambda e: {"event_date": "01-01-2000", "region": "X", "series": [], "note": "no series"})
    d = events.replay_event("E1")
    assert d["steps"] == [] and d["note"] and "REPLAY" in d["label"]


def test_replay_scores_real_series_hour_by_hour(monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    from backend.routers import events
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE historical_events (event_id TEXT, hex_id TEXT, type TEXT, severity TEXT)")
    conn.execute("INSERT INTO historical_events VALUES ('E1','h1','landslide','high')")

    @contextmanager
    def fake_db():
        yield conn
    monkeypatch.setattr(events, "get_db", fake_db)
    series = [{"time": f"2000-01-01T{h:02d}:00:00", "rainfall_mm": r} for h, r in enumerate([0, 5, 40, 60])]
    monkeypatch.setattr(events, "get_event_rainfall_window",
                        lambda e: {"event_date": "x", "region": "X", "series": series, "note": "real"})
    monkeypatch.setattr(events, "_terrain_for_hex", lambda h: ({"slope_deg": 32.0, "hand_m": 50.0}, "test"))
    d = events.replay_event("E1")
    assert [s["rainfall_24h"] for s in d["steps"]] == [0, 5, 45, 105]
    assert d["steps"][-1]["risk_score"] >= d["steps"][0]["risk_score"]
    assert "soil_saturation" in d["steps"][0]["missing_inputs"]


def test_simulated_observations_never_feed_the_sensor_path(monkeypatch):
    import json
    import sqlite3
    from contextlib import contextmanager
    from backend import database, rainfall
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE observations (hex_id TEXT, timestamp TEXT, provenance TEXT, dynamic_features TEXT)")
    now = datetime.now(timezone.utc).isoformat()
    feats = json.dumps({"rainfall_1h": 28.0, "soil_moisture_surface": 0.5, "soil_saturation_ratio": 0.92})
    conn.execute("INSERT INTO observations VALUES ('h1', ?, 'SIMULATED', ?)", (now, feats))

    @contextmanager
    def fake_db():
        yield conn
    monkeypatch.setattr(database, "get_db", fake_db)
    assert rainfall._get_sensor_rainfall("h1") is None
    assert rainfall._get_sensor_soil_moisture("h1") is None
    conn.execute("INSERT INTO observations VALUES ('h1', ?, 'REAL_RECONSTRUCTED', ?)", (now, feats))
    assert rainfall._get_sensor_rainfall("h1")["rainfall_1h"] == 28.0


def test_cached_rainfall_is_never_far_away_or_stale(monkeypatch, tmp_path):
    import json
    from backend import rainfall
    now = datetime.now(timezone.utc)
    snap = {"fetched_at": now.isoformat(), "locations": [
        {"location": "Mundakkai", "lat": 11.51, "lon": 76.05,
         "series": {"time": ["2026-01-01T00:00"], "precipitation_mm": [5.0]}}]}
    (tmp_path / "cached_demo_snapshot.json").write_text(json.dumps(snap))
    monkeypatch.setattr(rainfall, "_CACHE_DIR", tmp_path)
    assert rainfall._load_cached_rainfall(11.52, 76.06) is not None          # 1-2 km away, fresh: usable
    assert rainfall._load_cached_rainfall(30.5, 79.0) is None                 # Uttarakhand: too far
    snap["fetched_at"] = "2026-01-01T00:00:00+00:00"
    (tmp_path / "cached_demo_snapshot.json").write_text(json.dumps(snap))
    assert rainfall._load_cached_rainfall(11.52, 76.06) is None               # too old


def test_live_failure_uses_last_good_reading_for_the_same_cell(monkeypatch):
    import httpx
    from backend import rainfall
    monkeypatch.setattr(rainfall, "_LAST_GOOD", {})
    monkeypatch.setattr(rainfall, "_load_cached_rainfall", lambda lat, lon: None)
    fn = getattr(rainfall.fetch_open_meteo_rainfall, "__wrapped__", rainfall.fetch_open_meteo_rainfall)

    class R:
        def raise_for_status(self): pass
        def json(self): return {"hourly": {"time": ["t0"], "precipitation": [1.5]}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    assert fn(30.51, 79.01)[1] == "open_meteo_live"

    def boom(*a, **k): raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", boom)
    series, src = fn(30.52, 79.02)                                           # same ~10 km cell
    assert src == "open_meteo_cached" and series["precipitation"] == [1.5]
    assert fn(11.5, 76.0)[1] == "unavailable"                                 # nothing for another place


def test_village_index_names_hexes_inside_and_near_villages(monkeypatch, tmp_path):
    import geopandas as gpd
    import h3
    from shapely.geometry import box
    from backend import village_index as vi
    g = gpd.GeoDataFrame({"village_id": ["v1"], "name": ["Tandari"]},
                         geometry=[box(77.10, 31.90, 77.14, 31.94)], crs="EPSG:4326")
    g.to_file(tmp_path / "t-r.gpkg", layer="villages", driver="GPKG")
    monkeypatch.setattr(vi, "GPKG_DIR", tmp_path)
    monkeypatch.setattr(vi, "_CACHE", {})
    inside = vi.village_for_hex("t-r", h3.latlng_to_cell(31.92, 77.12, 8))
    assert inside == {"village_id": "v1", "name": "Tandari", "nearest": False}
    far = vi.village_for_hex("t-r", h3.latlng_to_cell(32.3, 77.5, 8))
    assert far["name"] == "Tandari" and far["nearest"] is True
    assert vi.village_for_hex("no-such-region", "x") is None
