"""tests for: evacuation advisory, village persistence cycle + /village/drafts, scoring-region opt-in,
and ml/dataset/explain.py (tree SHAP additivity and grouping)."""
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml" / "dataset"))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from backend import risk_engine, village_cycle as vc  # noqa: E402
from backend.routers import evacuation as evac, village as vapi  # noqa: E402
import explain  # noqa: E402

RAT = dict(alert_tier="Orange", alert_value=60.0, alert_driver="footprint", name="V", boundary_quality="osm")


def layers_with(*vs):
    return vapi.RegionLayers("demo", villages=[dict(village_id=i, name=i, geometry=g, population=None,
                                                    boundary_quality="osm") for i, g in vs])


# ---------------------------------------------------------------- evacuation
@pytest.fixture()
def evac_client(monkeypatch):
    lay = layers_with(("wy", Point(76.05, 11.51).buffer(0.01)), ("far", Point(92.0, 25.9).buffer(0.01)))
    monkeypatch.setattr(vapi, "load_region_layers", lambda region: lay)
    monkeypatch.setattr(evac, "load_shelters", lambda: [
        dict(shelter_id="S1", name="School A", lat=11.5185, lon=76.0524),
        dict(shelter_id="S2", name="School B", lat=11.5143, lon=76.0498)])
    app = fastapi.FastAPI()
    app.include_router(evac.router)
    return TestClient(app)


def test_nearby_shelters_sorted_and_labelled_not_routed(evac_client):
    j = evac_client.get("/evacuation/wy", params={"region": "demo"}).json()
    d = [s["distance_km"] for s in j["shelters"]]
    assert d == sorted(d) and len(d) == 2 and d[0] < 5
    assert j["advisory_only"] and j["blocked_roads_checked"] is False and "straight-line" in j["basis"]


def test_far_village_gets_no_shelter_not_one_hundreds_of_km_away(evac_client):
    j = evac_client.get("/evacuation/far", params={"region": "demo"}).json()
    assert j["shelters"] == [] and "none offered" in j["note"] and j["shelters_in_database"] == 2


def test_unknown_village_404(evac_client):
    assert evac_client.get("/evacuation/nope", params={"region": "demo"}).status_code == 404


# ---------------------------------------------------------------- village persistence cycle
def test_cycle_needs_two_cycles_and_reports_draft():
    tr = vc.VillagePersistenceTracker()
    lay = layers_with(("v1", Point(0, 0).buffer(1)))
    comp = lambda v, l: dict(RAT)                                                   # noqa: E731
    assert vc.run_village_cycle("demo", tracker=tr, compute=comp, layers=lay) == []
    d = vc.run_village_cycle("demo", tracker=tr, compute=comp, layers=lay)
    assert len(d) == 1 and d[0]["draft_tier"] == "Orange" and d[0]["village_id"] == "v1"
    assert vc.LAST_RUN["demo"]["drafts"] == d


def test_cold_start_records_nothing_and_returns_no_draft():
    tr = vc.VillagePersistenceTracker()
    lay = layers_with(("v1", Point(0, 0).buffer(1)))
    comp = lambda v, l: dict(RAT)                                                   # noqa: E731
    for _ in range(3):
        assert vc.run_village_cycle("demo", cold_start=True, tracker=tr, compute=comp, layers=lay) == []
    assert tr.history == {}                                  # nothing counted during cold start
    assert vc.run_village_cycle("demo", tracker=tr, compute=comp, layers=lay) == []   # streak starts now


def test_unscored_villages_are_skipped():
    tr = vc.VillagePersistenceTracker()
    lay = layers_with(("v1", Point(0, 0).buffer(1)))
    comp = lambda v, l: dict(alert_tier=None, alert_value=None)                     # noqa: E731
    for _ in range(3):
        assert vc.run_village_cycle("demo", tracker=tr, compute=comp, layers=lay) == []
    assert tr.history == {}


def test_drafts_endpoint_is_reporting_only(monkeypatch):
    monkeypatch.setattr(vc, "TRACKER", vc.VillagePersistenceTracker())
    vc.TRACKER.update("v1", "landslide", "Orange")
    vc.TRACKER.update("v1", "landslide", "Orange")
    app = fastapi.FastAPI()
    app.include_router(vapi.router)
    j = TestClient(app).get("/village/drafts").json()
    assert j["open_drafts"] == ["v1|landslide"] and "nothing is published" in j["note"]


# ---------------------------------------------------------------- scoring-region opt-in
def test_scoring_regions_default_empty_and_env_parsed(monkeypatch):
    monkeypatch.delenv("HYDRASENSE_SCORE_REGIONS", raising=False)
    assert risk_engine.scoring_regions() == []
    monkeypatch.setenv("HYDRASENSE_SCORE_REGIONS", " ribhoi-ml , idukki-kl ,")
    assert risk_engine.scoring_regions() == ["ribhoi-ml", "idukki-kl"]


def test_cycle_scores_only_legacy_and_opted_in_hexes(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE hexes (hex_id TEXT, region_code TEXT)")
    conn.executemany("INSERT INTO hexes VALUES (?,?)", [("legacy1", ""), ("legacy2", None),
                                                        ("rib1", "ribhoi-ml"), ("idk1", "idukki-kl")])

    @contextmanager
    def fake_db():
        yield conn
    scored = []
    monkeypatch.setattr(risk_engine, "get_db", fake_db)
    monkeypatch.setattr(risk_engine, "compute_and_store_risk", lambda h: scored.append(h) or {"ok": 1})
    monkeypatch.delenv("HYDRASENSE_SCORE_REGIONS", raising=False)
    risk_engine.run_cycle_all_regions()
    assert sorted(scored) == ["legacy1", "legacy2"]                      # new regions NOT scored by default
    scored.clear()
    monkeypatch.setenv("HYDRASENSE_SCORE_REGIONS", "ribhoi-ml")
    risk_engine.run_cycle_all_regions()
    assert sorted(scored) == ["legacy1", "legacy2", "rib1"]


# ---------------------------------------------------------------- explain
@pytest.fixture(scope="module")
def tiny_model():
    xgboost = pytest.importorskip("xgboost")
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"rain_24h": rng.gamma(2, 10, 400), "rain_6h": rng.gamma(2, 4, 400),
                      "slope_deg": rng.uniform(0, 40, 400), "imerg_1d": rng.gamma(2, 8, 400)})
    y = (X.rain_24h + rng.normal(0, 4, 400) > 25).astype(int)
    m = xgboost.XGBClassifier(n_estimators=40, max_depth=3, random_state=0, verbosity=0).fit(X, y)
    return m, X


def test_tree_shap_is_additive_and_ranks_the_true_driver(tiny_model):
    import xgboost as xgb
    m, X = tiny_model
    c = explain.contributions(m, X.head(50))
    margin = m.get_booster().predict(xgb.DMatrix(X.head(50).to_numpy(float), feature_names=list(X.columns)),
                                     output_margin=True)
    assert np.allclose(c.sum(axis=1).to_numpy(), margin, atol=1e-4)      # contributions + bias = margin
    assert c.drop(columns="bias").abs().mean().idxmax() == "rain_24h"


def test_group_contributions_preserve_the_total(tiny_model):
    m, X = tiny_model
    c = explain.contributions(m, X.head(20))
    g = explain.group_contributions(c)
    assert np.allclose(g.sum(axis=1), c.sum(axis=1))
    assert "recent rain" in g.columns and "terrain" in g.columns and "bias" in g.columns
    assert "rain_24h" not in g.columns and "rain_6h" not in g.columns    # folded into the group


def test_top_reasons_excludes_bias_and_is_sorted(tiny_model):
    m, X = tiny_model
    c = explain.contributions(m, X.head(5))
    r = explain.top_reasons(c.iloc[0], n=2)
    assert len(r) == 2 and abs(r[0][1]) >= abs(r[1][1]) and all(k != "bias" for k, _ in r)
