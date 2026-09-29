"""tests/test_confidence_v2.py -- v2 Sec. 9.2 four-factor confidence + reasons (pure logic)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import confidence as cf  # noqa: E402

SENSOR = {"tier": 0, "coverage": "point"}
SAT = {"tier": 1, "coverage": "satellite_only"}
GAUGE = {"tier": 1, "coverage": "gauge_merged"}
CACHED = {"tier": 2, "coverage": "satellite_only"}
STATIC = {"tier": 3, "coverage": "static"}


def test_v2_worked_example_uncalibrated_arithmetic():
    # v2 Sec. 9.2: 0.91 x 0.77 x 0.75 x 1.00 = 52.6 (their example uses C_in = 1.00)
    out = cf.compute_confidence(0.91, 0.23, False, {"rainfall": SENSOR, "soil": SENSOR},
                                c_cal_uncalibrated=0.75)
    assert out["confidence_score"] == pytest.approx(52.6, abs=0.06)
    assert out["confidence_factors"] == {"model_probability": 91, "engine_uncertainty": 77,
                                         "calibration": 75, "input_coverage": 100}


def test_v2_worked_example_calibrated_sensor():
    out = cf.compute_confidence(0.91, 0.15, True, {"rainfall": SENSOR, "soil": SENSOR})
    assert out["confidence_score"] == pytest.approx(77.35, abs=0.06)   # exact 77.35; v2 prints 77.4 (rounded) -> 77


def test_same_risk_lower_confidence_for_cached_inputs():
    good = cf.compute_confidence(0.9, 0.1, True, {"rainfall": GAUGE, "soil": GAUGE})
    bad = cf.compute_confidence(0.9, 0.1, True, {"rainfall": GAUGE, "soil": CACHED})
    assert bad["confidence_score"] < good["confidence_score"]
    assert bad["limiting_input_layer"] == "soil"
    assert bad["primary_reason"] == "cached soil layer"


def test_c_in_is_weakest_link_and_monotone():
    levels = [cf.input_coverage({"rainfall": b})[0] for b in (SENSOR, GAUGE, SAT, CACHED, STATIC)]
    assert levels == sorted(levels, reverse=True) and levels[0] == 1.0
    c, lim, per = cf.input_coverage({"rainfall": SENSOR, "soil": STATIC})
    assert lim == "soil" and c == per["soil"]


def test_unknown_or_missing_layers_never_look_good():
    assert cf.layer_level({}) == cf.UNKNOWN_LAYER_LEVEL
    assert cf.input_coverage({})[0] == cf.UNKNOWN_LAYER_LEVEL
    assert cf.layer_level({"tier": 9, "coverage": "?"}) == cf.UNKNOWN_LAYER_LEVEL


def test_accepts_badge_objects():
    class Badge:  # duck-typed like backend.rainfall.RainfallLayerBadge
        tier, coverage = 1, "satellite_only"
    assert cf.layer_level(Badge()) == cf.C_IN_LEVELS[(1, "satellite_only")]


def test_calibration_reason_and_default_is_provisional_not_loro():
    out = cf.compute_confidence(0.9, 0.0, False, {"rainfall": SENSOR})
    assert out["confidence_factors"]["calibration"] == 75          # NOT silently 100 from LORO
    assert out["c_cal_source"] == "provisional_default"
    assert out["primary_reason"] == "no local historical calibration"
    assert "c_cal_uncalibrated" in out["provisional_constants"]


def test_fitted_c_cal_is_labelled_fitted():
    out = cf.compute_confidence(0.9, 0.0, False, {"rainfall": SENSOR}, c_cal_uncalibrated=0.9)
    assert out["c_cal_source"] == "fitted" and out["confidence_factors"]["calibration"] == 90


def test_reasons_sorted_by_shortfall_and_all_local_case():
    out = cf.compute_confidence(0.6, 0.3, False, {"rainfall": SAT})
    gaps = [r["shortfall_pct"] for r in out["reasons"]]
    assert gaps == sorted(gaps, reverse=True) and len(gaps) == 4
    perfect = cf.compute_confidence(1.0, 0.0, True, {"rainfall": SENSOR})
    assert perfect["confidence_score"] == 100.0 and perfect["reasons"] == []
    assert perfect["primary_reason"] == "all inputs local and calibrated"


def test_fs_penalty_formula_cap_and_widening():
    # (1.11 - 0.82) / (2 x 0.96) = 0.151
    assert cf.fs_penalty(0.82, 0.96, 1.11, True) == pytest.approx(0.151, abs=0.001)
    assert cf.fs_penalty(0.82, 0.96, 1.11, False) == pytest.approx(0.151 * 1.5, abs=0.002)
    assert cf.fs_penalty(0.1, 0.5, 5.0, True) == cf.ENG_PENALTY_CAP          # capped
    assert cf.fs_penalty(0.1, 0.5, 5.0, False) == cf.ENG_PENALTY_CAP          # still capped
    assert cf.fs_penalty(None, None, None) == cf.ENG_PENALTY_CAP              # unknown -> worst case


def test_flood_penalty_and_unknown():
    assert cf.flood_penalty(8.0, 10.0, 12.0) == pytest.approx(0.2)
    assert cf.flood_penalty(None, 10.0, 12.0) == cf.ENG_PENALTY_CAP


def test_inputs_are_clipped_and_score_bounded():
    out = cf.compute_confidence(1.7, 5.0, True, {"rainfall": SENSOR})
    assert 0.0 <= out["confidence_score"] <= 100.0
    assert out["confidence_factors"]["model_probability"] == 100
    assert out["confidence_factors"]["engine_uncertainty"] == 40           # penalty capped at 0.6
    assert cf.compute_confidence(-1.0, 0.0, True, {"rainfall": SENSOR})["confidence_score"] == 0.0


def test_label_is_not_a_probability_claim():
    out = cf.compute_confidence(0.8, 0.1, True, {"rainfall": GAUGE})
    assert "not a probability" in out["label"]
    assert cf.confidence_band(80) == "high" and cf.confidence_band(50) == "medium" and cf.confidence_band(10) == "low"
