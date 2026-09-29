"""
tests/test_village_api.py -- /village/* and /confidence/{hex}/factors wiring.

No network, no real DB: the region loader and hex-risk reader are monkeypatched with a synthetic
region (steep terrain, one source hex above a village), and the confidence route reads a temporary
in-memory SQLite database.
"""
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient            # noqa: E402
from shapely.geometry import Polygon                  # noqa: E402
from shapely.ops import unary_union                   # noqa: E402
import h3                                             # noqa: E402

import test_village_rollup as rollup_fixture          # noqa: E402
from backend.routers import village as village_api   # noqa: E402
from backend.routers import confidence as conf_api    # noqa: E402


def _cell_polygon(cell):
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)])


@pytest.fixture()
def client_village(monkeypatch):
    cells, elev, footprint, ls, sl, src = rollup_fixture.setup(22)
    geom = unary_union([_cell_polygon(c) for c in footprint])
    layers = village_api.RegionLayers(
        "demo-region",
        villages=[dict(village_id="V1", name="Demo", geometry=geom, population=1000.0, boundary_quality="osm"),
                  dict(village_id="V2", name="Far", geometry=_cell_polygon(src), population=50.0,
                       boundary_quality="voronoi_approx")],
        elevation=elev, slope_deg=sl)
    monkeypatch.setattr(village_api, "load_region_layers", lambda region: layers)
    monkeypatch.setattr(village_api, "latest_hex_risks", lambda ids: {
        h: dict(risk_score=ls[h], tier=None, data_source="open_meteo_live") for h in ids if h in ls})
    app = fastapi.FastAPI()
    app.include_router(village_api.router)
    return TestClient(app), src


def test_village_risk_reports_upslope_source_and_states_flood_gap(client_village):
    client, src = client_village
    r = client.get("/village/V1/risk", params={"region": "demo-region"})
    assert r.status_code == 200
    j = r.json()
    assert j["alert_driver"] == "upslope_source" and j["alert_value"] == 80.0
    assert j["alert_tier"] == "Red" and j["source_hex"] == src
    assert j["footprint_p90"] == 20.0 and j["boundary_quality"] == "osm"
    assert j["flood"] is None and "not built" in j["flood_note"]        # no invented flood value
    assert j["data_sources"] == ["open_meteo_live"] and j["footprint_hexes_scored"] > 0
    assert "risk_only" in j["priority_basis"]


def test_priority_is_sorted_by_risk_and_labels_its_basis(client_village):
    client, _ = client_village
    j = client.get("/village/priority", params={"region": "demo-region"}).json()
    values = [v["alert_value"] for v in j["villages"]]
    assert values == sorted(values, reverse=True) and j["villages"][0]["priority_rank"] == 1
    assert j["priority_basis"].startswith("risk_only") and j["count"] == 2


def test_unknown_village_is_404(client_village):
    client, _ = client_village
    assert client.get("/village/NOPE/risk", params={"region": "demo-region"}).status_code == 404


def test_unscored_footprint_gives_null_value_with_note(monkeypatch, client_village):
    client, _ = client_village
    monkeypatch.setattr(village_api, "latest_hex_risks", lambda ids: {})
    j = client.get("/village/V1/risk", params={"region": "demo-region"}).json()
    assert j["alert_value"] is None and j["footprint_hexes_scored"] == 0 and "no scored hexes" in j["note"]


def test_not_onboarded_region_is_404_not_fabricated(monkeypatch, tmp_path):
    monkeypatch.setattr(village_api, "GPKG_DIR", tmp_path)
    app = fastapi.FastAPI()
    app.include_router(village_api.router)
    r = TestClient(app).get("/village/priority", params={"region": "nowhere"})
    assert r.status_code == 404 and "onboarding" in r.json()["detail"]


# ------------------------------------------------------------------ confidence factors
@pytest.fixture()
def client_conf(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE risk_scores(id INTEGER PRIMARY KEY, hex_id TEXT, timestamp TEXT, risk_score REAL,
            tier TEXT, confidence_score REAL, data_source TEXT, sensor_adjusted INTEGER);
        CREATE TABLE hexes(hex_id TEXT, static_features TEXT);
    """)

    @contextmanager
    def fake_db():
        yield conn
    monkeypatch.setattr(conf_api, "get_db", fake_db)
    monkeypatch.setattr(conf_api, "_load_c_cal_uncalibrated", lambda: 1.0)   # the (untrusted) LORO value
    app = fastapi.FastAPI()
    app.include_router(conf_api.router)
    return TestClient(app), conn


def _seed(conn, hex_id, conf, source, sensor, static):
    conn.execute("INSERT INTO risk_scores(hex_id,timestamp,risk_score,tier,confidence_score,data_source,sensor_adjusted)"
                 " VALUES (?,?,?,?,?,?,?)", (hex_id, "2026-09-30T00:00:00", 82.0, "Red", conf, source, sensor))
    conn.execute("INSERT INTO hexes VALUES (?,?)", (hex_id, json.dumps(static)))


def test_factors_endpoint_four_factors_and_assumptions(client_conf):
    client, conn = client_conf
    _seed(conn, "h1", 60.0, "open_meteo_live", 0,
          {"factor_of_safety": 0.96, "factor_of_safety_min": 0.82, "factor_of_safety_max": 1.11,
           "has_local_calibration": False})
    j = client.get("/confidence/h1/factors").json()
    f = j["confidence_factors"]
    assert set(f) == {"model_probability", "engine_uncertainty", "calibration", "input_coverage"}
    assert f["calibration"] == 75                      # provisional 0.75, NOT the LORO 1.0
    assert f["input_coverage"] == 85                   # live satellite-only
    assert j["c_cal_source"] == "provisional_default"
    assert any("P_class reconstructed" in a for a in j["assumptions"])
    assert any("soil layer assumed" in a for a in j["assumptions"])
    assert "not a probability" in j["label"] and j["primary_reason"]


def test_missing_fs_band_is_worst_case_not_a_default(client_conf):
    client, conn = client_conf
    _seed(conn, "h2", 50.0, "open_meteo_live", 0, {})
    j = client.get("/confidence/h2/factors").json()
    assert j["confidence_factors"]["engine_uncertainty"] == 40             # 1 - 0.6 cap
    assert "worst case" in j["engine_uncertainty_source"]


def test_cached_source_and_sensor_adjustment_change_c_in(client_conf):
    client, conn = client_conf
    _seed(conn, "h3", 50.0, "open_meteo_cached", 0, {})
    _seed(conn, "h4", 50.0, "sensor", 1, {})
    assert client.get("/confidence/h3/factors").json()["confidence_factors"]["input_coverage"] == 65
    j = client.get("/confidence/h4/factors").json()
    assert j["confidence_factors"]["input_coverage"] == 100 and j["limiting_input_layer"] in ("rainfall", "soil")


def test_unknown_data_source_is_flagged_and_low(client_conf):
    client, conn = client_conf
    _seed(conn, "h5", 50.0, "mystery", 0, {})
    j = client.get("/confidence/h5/factors").json()
    assert j["confidence_factors"]["input_coverage"] == 40
    assert any("unrecognised data_source" in a for a in j["assumptions"])


def test_unknown_hex_is_404(client_conf):
    client, _ = client_conf
    assert client.get("/confidence/none/factors").status_code == 404
