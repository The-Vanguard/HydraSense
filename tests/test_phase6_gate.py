"""
tests/test_phase6_gate.py
Phase 6 Validation Gate — Acceptance Tests.

SRS §25 / Migration Plan §6 criteria:
  AC-1: frozen calibration.json exists and has required keys.
  AC-2: LOEO detection rate is reported (non-null) and >= 0.0 (not fabricated).
  AC-3: LORO detection rate is reported; C_cal empirical value is present.
  AC-4: Spatial block summary exists with cluster_method and n_clusters.
  AC-5: calibration.json frozen_date is a valid ISO date string.
  AC-6: Tier thresholds in calibration.json match SRS §10.4 baseline
        OR are lower (recalibrated downward only, never upward).
  AC-7: confidence_formula is present in calibration.json.
  AC-8: No SIMULATED rows in loeo_results.json (provenance gate).

These are READ-ONLY tests — they check frozen artifacts, never recompute.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_VAL = ROOT / "data" / "validation"
CALIB    = DATA_VAL / "calibration.json"
LOEO_SUM = DATA_VAL / "loeo_summary.json"
LORO_SUM = DATA_VAL / "loro_summary.json"
SPBLK    = DATA_VAL / "spatial_block_summary.json"
LOEO_RES = DATA_VAL / "loeo_results.json"

SRS_ORANGE_MIN = 55.0  # §10.4 baseline
SRS_RED_MIN    = 75.0  # §10.4 baseline


# ---------------------------------------------------------------------------
# AC-1: calibration.json exists and has required top-level keys
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CALIB.exists(), reason="calibration.json not yet produced — run calibrate_thresholds.py")
def test_calibration_file_has_required_keys():
    """AC-1: calibration.json must exist and contain all required sections."""
    with open(CALIB, encoding="utf-8") as f:
        cal = json.load(f)

    required = {"frozen_date", "loeo", "loro", "spatial_block",
                "tier_thresholds", "confidence_factors"}
    missing = required - set(cal.keys())
    assert not missing, f"calibration.json missing keys: {missing}"


# ---------------------------------------------------------------------------
# AC-2: LOEO detection rate is a real number (not fabricated 1.0 with 0 events)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LOEO_SUM.exists(), reason="loeo_summary.json not found")
def test_loeo_detection_rate_reported():
    """AC-2: LOEO detection rate is non-null and > 0 events were evaluated."""
    with open(LOEO_SUM, encoding="utf-8") as f:
        loeo = json.load(f)

    dr = loeo.get("detection_rate")
    n  = loeo.get("loeo_n_events", 0)
    assert dr is not None, "detection_rate is null in loeo_summary.json"
    assert n > 0, f"loeo_n_events={n} — no events were evaluated"
    assert 0.0 <= dr <= 1.0, f"detection_rate={dr} out of [0,1]"


# ---------------------------------------------------------------------------
# AC-3: LORO C_cal is present and a valid float
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LORO_SUM.exists(), reason="loro_summary.json not found")
def test_loro_c_cal_present():
    """AC-3: LORO summary must contain c_cal_calibration with empirical value."""
    with open(LORO_SUM, encoding="utf-8") as f:
        loro = json.load(f)

    c_cal_block = loro.get("c_cal_calibration", {})
    c_emp = c_cal_block.get("c_cal_empirical")
    assert c_emp is not None, "c_cal_empirical missing from loro_summary.json"
    assert 0.0 < c_emp <= 1.5, f"c_cal_empirical={c_emp} outside plausible range"


# ---------------------------------------------------------------------------
# AC-4: Spatial block summary exists with cluster method
# ---------------------------------------------------------------------------

def test_spatial_block_summary_exists():
    """AC-4: spatial_block_summary.json must exist (even if all folds skipped)."""
    assert SPBLK.exists(), (
        "spatial_block_summary.json not found — run ml/validation/spatial_block.py"
    )
    with open(SPBLK, encoding="utf-8") as f:
        spblk = json.load(f)

    assert "cluster_method" in spblk, "cluster_method missing from spatial_block_summary.json"
    assert "spatial_block_n_clusters" in spblk


# ---------------------------------------------------------------------------
# AC-5: calibration.json frozen_date is a valid ISO date
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CALIB.exists(), reason="calibration.json not yet produced")
def test_calibration_frozen_date_valid():
    """AC-5: frozen_date must be a parseable ISO-8601 date (YYYY-MM-DD)."""
    with open(CALIB, encoding="utf-8") as f:
        cal = json.load(f)

    frozen = cal.get("frozen_date")
    assert frozen is not None, "frozen_date missing from calibration.json"
    try:
        date.fromisoformat(frozen)
    except ValueError:
        pytest.fail(f"frozen_date='{frozen}' is not a valid ISO date")


# ---------------------------------------------------------------------------
# AC-6: Tier thresholds never moved UP from SRS baseline
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CALIB.exists(), reason="calibration.json not yet produced")
def test_tier_thresholds_not_inflated():
    """AC-6: Orange/Red thresholds must not exceed SRS §10.4 baselines."""
    with open(CALIB, encoding="utf-8") as f:
        cal = json.load(f)

    thresholds = cal.get("tier_thresholds", {}).get("thresholds", {})
    orange_min = thresholds.get("orange_min", SRS_ORANGE_MIN)
    red_min    = thresholds.get("red_min",    SRS_RED_MIN)

    assert orange_min <= SRS_ORANGE_MIN, (
        f"orange_min={orange_min} > SRS baseline {SRS_ORANGE_MIN} — "
        "thresholds must only be lowered (more sensitive), never raised"
    )
    assert red_min <= SRS_RED_MIN, (
        f"red_min={red_min} > SRS baseline {SRS_RED_MIN}"
    )


# ---------------------------------------------------------------------------
# AC-7: confidence_formula is recorded
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CALIB.exists(), reason="calibration.json not yet produced")
def test_confidence_formula_documented():
    """AC-7: confidence_factors block must document the formula."""
    with open(CALIB, encoding="utf-8") as f:
        cal = json.load(f)

    formula = cal.get("confidence_factors", {}).get("confidence_formula", "")
    assert "P_class" in formula, (
        f"confidence_formula missing P_class: '{formula}'"
    )
    assert "C_cal" in formula, (
        f"confidence_formula missing C_cal: '{formula}'"
    )


# ---------------------------------------------------------------------------
# AC-8: No SIMULATED rows in LOEO per-event results (provenance gate)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not LOEO_RES.exists(), reason="loeo_results.json not found")
def test_no_simulated_provenance_in_loeo():
    """AC-8: provenance gate — SIMULATED rows must not appear in LOEO results."""
    with open(LOEO_RES, encoding="utf-8") as f:
        results = json.load(f)

    simulated = [
        r for r in results
        if str(r.get("provenance", "")).upper() == "SIMULATED"
    ]
    assert not simulated, (
        f"{len(simulated)} LOEO result rows carry provenance=SIMULATED — "
        "the leakage gate failed: simulated data must never enter validation."
    )
