"""tests/test_physics_risk.py -- the physics-first hazard index (backend/physics_risk.py)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import physics_risk as pr  # noqa: E402

SOIL = dict(soil_c_prime_kpa=8.0, soil_phi_deg=28.0, soil_z_m=2.5, soil_gamma_kn_m3=18.5)


def feats(**kw):
    base = dict(slope_deg=32.0, hand_m=80.0, soil_saturation_ratio=0.85, has_local_calibration=False, **SOIL)
    base.update(kw)
    return base


DRY = dict(rainfall_1h=0.0, rainfall_3h=0.0, rainfall_6h=0.0, rainfall_24h=0.0, rainfall_72h_antecedent=0.0)
STORM = dict(rainfall_1h=40.0, rainfall_3h=90.0, rainfall_6h=150.0, rainfall_24h=260.0, rainfall_72h_antecedent=420.0)


def test_tier_cut_points():
    assert [pr.tier_from_score(x) for x in (0, 29.9, 30, 54.9, 55, 74.9, 75, 100)] == \
        ["Green", "Green", "Yellow", "Yellow", "Orange", "Orange", "Red", "Red"]


def test_deterministic_for_the_same_input():
    a, b = pr.score_features(feats(**STORM)), pr.score_features(feats(**STORM))
    assert a["risk_score"] == b["risk_score"]


def test_dry_day_on_a_steep_saturated_slope_cannot_alert():
    out = pr.score_features(feats(**DRY))
    assert out["risk_score"] <= 25.0 and out["tier"] == "Green" and out["trigger"] == 0.0


def test_heavy_rain_on_a_steep_saturated_slope_reaches_orange_or_red():
    out = pr.score_features(feats(**STORM))
    assert out["tier"] in ("Orange", "Red") and out["risk_score"] > 55 and out["hazard"] == "landslide"
    assert out["controlling_duration_h"] in (1, 3, 6, 24, 72) and out["trigger_ratio"] > 1


def test_monotone_in_rainfall_and_in_slope():
    lo = pr.score_features(feats(rainfall_24h=20.0))["risk_score"]
    hi = pr.score_features(feats(rainfall_24h=200.0))["risk_score"]
    assert hi > lo
    flat = pr.score_features(feats(slope_deg=4.0, **STORM))["risk_score"]
    steep = pr.score_features(feats(slope_deg=35.0, **STORM))["risk_score"]
    assert steep > flat


def test_different_terrain_gives_different_scores_not_one_constant():
    scores = {round(pr.score_features(feats(slope_deg=s, **STORM))["risk_score"], 2) for s in (5, 12, 20, 30, 40)}
    assert len(scores) >= 4                                    # the old model returned one value for all hexes


def test_flood_term_uses_hand_and_can_control():
    out = pr.score_features(feats(slope_deg=3.0, hand_m=1.0, **STORM))
    assert out["hazard"] == "flood" and out["index_flood"] > out["index_landslide"]
    assert out["tier"] in ("Orange", "Red")
    assert pr.score_features(feats(slope_deg=3.0, hand_m=80.0, **STORM))["index_flood"] == 0.0


def test_missing_inputs_are_listed_never_defaulted():
    out = pr.score_features(dict(slope_deg=30.0, **SOIL))
    assert set(out["missing_inputs"]) >= {"rainfall", "soil_saturation", "hand_m"}
    assert out["trigger"] == 0.0 and out["p_fs_lt1"] is None
    assert "soil_parameters" in pr.score_features(dict(slope_deg=30.0, soil_saturation_ratio=0.8, **DRY))["missing_inputs"]
    assert "slope" in pr.score_features(dict(**DRY))["missing_inputs"]


def test_contributions_add_up_to_the_score():
    for f in (feats(**STORM), feats(slope_deg=3.0, hand_m=1.0, **STORM), feats(**DRY)):
        out = pr.score_features(f)
        assert sum(out["feature_contributions"].values()) == pytest.approx(out["risk_score"], abs=0.05)


def test_model_interface_matches_what_the_risk_engine_reads():
    out = pr.PhysicsRiskModel().predict_one(feats(**STORM))
    for k in ("risk_score", "tier", "confidence_score", "feature_contributions"):
        assert k in out
    assert 0 <= out["confidence_score"] <= 100 and out["method"] == "physics_first_index_v0"
    assert "not a model probability" in out["confidence_note"]


def test_missing_inputs_lower_confidence():
    m = pr.PhysicsRiskModel()
    layers = {"rainfall": {"tier": 1, "coverage": "satellite_only"}, "soil": {"tier": 1, "coverage": "satellite_only"}}
    full = m.predict_one({**feats(**STORM), "_input_layers": layers})
    partial = m.predict_one({**{k: v for k, v in feats(**STORM).items() if k != "soil_saturation_ratio"},
                             "_input_layers": layers})
    assert partial["confidence_score"] < full["confidence_score"]


def test_engine_selects_physics_by_default(monkeypatch):
    from backend import risk_engine
    monkeypatch.setattr(risk_engine, "_model_cache", None)
    monkeypatch.delenv("HYDRASENSE_RISK_MODEL", raising=False)
    assert risk_engine.get_model().name == "physics_first_index_v0"
    monkeypatch.setattr(risk_engine, "_model_cache", None)      # do not leak the cached model to other tests


def test_layers_from_sources_maps_known_labels_and_flags_unknown():
    from backend.confidence import layers_from_sources
    lay = layers_from_sources("open_meteo_live", "open_meteo")
    assert lay["rainfall"]["tier"] == 1 and lay["soil"]["coverage"] == "satellite_only"
    assert layers_from_sources("mystery", "???")["rainfall"]["tier"] is None
    assert layers_from_sources("open_meteo_live", "model", sensor_adjusted=True)["soil"]["tier"] == 0
