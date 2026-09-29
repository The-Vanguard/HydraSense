"""
ml/validation/calibrate_thresholds.py
Phase 6 — Tier Cut-Point Recalibration & Confidence Factor Fitting.

SRS references:
  §10.2  risk_score formula (frozen — never touch this)
  §10.4  TIER_THRESHOLDS (Green 0-29 / Yellow 30-54 / Orange 55-74 / Red 75+)
  §11.2  tier label encoding used during training
  §11.3  confidence_score = 100 * P_class * (1 - FS_band_penalty) * C_cal

WHAT THIS MODULE DOES
---------------------
1. Load the frozen LOEO and LORO summary JSONs.
2. Derive empirical C_cal from LORO (already written there by loro.py).
3. Verify the tier thresholds match SRS §10.4 (no recalibration needed if
   LOEO detection rate >= 0.8 — we report, not blindly rewrite).
4. Compute FS_band_penalty thresholds from the validation sample set.
5. Write data/validation/calibration.json  — the single frozen record that
   the console validation panel reads at startup; this file NEVER changes
   at runtime (no live recomputation).

RULE: if frozen figures already exist AND were produced from a newer run
(by timestamp), skip recomputation and exit 0. Pass --force to override.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
LOEO_SUMMARY   = ROOT / "data" / "validation" / "loeo_summary.json"
LORO_SUMMARY   = ROOT / "data" / "validation" / "loro_summary.json"
SPATIAL_SUMMARY = ROOT / "data" / "validation" / "spatial_block_summary.json"
SAMPLES_PATH   = ROOT / "data" / "events" / "event_centered_samples.parquet"
CALIB_PATH     = ROOT / "data" / "validation" / "calibration.json"

# SRS §10.4 baseline thresholds (frozen; only overridden on hard evidence)
_BASELINE_THRESHOLDS = {
    "green_max":  29.0,
    "yellow_min": 30.0,
    "yellow_max": 54.0,
    "orange_min": 55.0,
    "orange_max": 74.0,
    "red_min":    75.0,
}
_DETECTION_RATE_RECALIBRATE_TRIGGER = 0.70  # only recalibrate if LOEO DR < 70%


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fit_fs_band_penalty_stats(samples_path: Path) -> dict[str, Any]:
    """
    Compute empirical FS-band penalty statistics from the sample set.
    Returns thresholds that map FS uncertainty to penalty magnitude.
    """
    if not samples_path.exists():
        return {"status": "samples_not_found", "penalty_mean": None, "penalty_p90": None}

    df = pd.read_parquet(samples_path)
    required = {"fs_low", "fs_high", "fs_mean"}
    missing  = required - set(df.columns)
    if missing:
        # Try to compute from FS columns if available
        if "fs_low" in df.columns and "fs_high" in df.columns:
            df["fs_band"] = df["fs_high"] - df["fs_low"]
        else:
            return {
                "status": "fs_columns_missing",
                "missing_cols": list(missing),
                "penalty_mean": None, "penalty_p90": None,
            }
    else:
        df["fs_band"] = df["fs_high"] - df["fs_low"]

    # penalty = clamp((band - 0.5) / 3.5, 0, 0.5) — from train_fusion_model.py
    penalty = ((df["fs_band"] - 0.5) / 3.5).clip(lower=0, upper=0.5)
    penalty = penalty.dropna()

    if penalty.empty:
        return {"status": "no_valid_rows", "penalty_mean": None, "penalty_p90": None}

    return {
        "status":           "ok",
        "n_rows":           int(len(penalty)),
        "penalty_mean":     round(float(penalty.mean()),   4),
        "penalty_median":   round(float(penalty.median()), 4),
        "penalty_p90":      round(float(np.percentile(penalty, 90)), 4),
        "penalty_max":      round(float(penalty.max()),    4),
        "fs_band_mean":     round(float(df["fs_band"].dropna().mean()), 4) if "fs_band" in df else None,
    }


def compute_calibration(force: bool = False, verbose: bool = True) -> dict[str, Any]:
    """
    Derive and freeze calibration figures from LOEO/LORO/spatial-block outputs.
    Returns the calibration dict (also written to data/validation/calibration.json).
    """
    # Check if existing frozen figures are newer than all inputs
    if not force and CALIB_PATH.exists():
        calib_mtime = CALIB_PATH.stat().st_mtime
        inputs = [LOEO_SUMMARY, LORO_SUMMARY, SPATIAL_SUMMARY, SAMPLES_PATH]
        if all((not p.exists()) or p.stat().st_mtime <= calib_mtime for p in inputs):
            if verbose:
                print(f"[calibrate] Frozen figures up-to-date ({CALIB_PATH}). "
                      "Use --force to recompute.")
            with open(CALIB_PATH, encoding="utf-8") as f:
                return json.load(f)

    if verbose:
        print("=" * 72)
        print("Phase 6 — Tier Cut-Point Recalibration & Confidence Factor Fitting")
        print("=" * 72)

    loeo  = _load_json(LOEO_SUMMARY)
    loro  = _load_json(LORO_SUMMARY)
    spblk = _load_json(SPATIAL_SUMMARY)

    # ── LOEO figures ──────────────────────────────────────────────────────────
    loeo_dr = loeo.get("detection_rate")
    loeo_n  = loeo.get("loeo_n_events", 0)
    loeo_timing = loeo.get("timing_error", {})

    # ── LORO C_cal ────────────────────────────────────────────────────────────
    loro_c_cal = loro.get("c_cal_calibration", {})
    c_cal_empirical   = loro_c_cal.get("c_cal_empirical", 0.75)
    c_cal_placeholder = loro_c_cal.get("c_cal_placeholder", 0.75)
    loro_dr = loro.get("detection_rate_aggregate")

    # ── Spatial block ─────────────────────────────────────────────────────────
    spblk_dr = spblk.get("mean_detection_rate")
    spblk_method = spblk.get("cluster_method", "not_run")

    # ── Tier threshold recalibration ──────────────────────────────────────────
    thresholds = dict(_BASELINE_THRESHOLDS)
    threshold_source = "srs_10.4_baseline_unchanged"
    threshold_note   = ""

    if loeo_dr is not None and loeo_dr < _DETECTION_RATE_RECALIBRATE_TRIGGER:
        # Evidence justifies recalibration: lower Orange threshold by 5 points
        thresholds["orange_min"] = max(45.0, thresholds["orange_min"] - 5.0)
        thresholds["yellow_max"] = thresholds["orange_min"] - 1.0
        threshold_source = "recalibrated_loeo_dr_below_threshold"
        threshold_note = (
            f"LOEO DR={loeo_dr:.1%} < {_DETECTION_RATE_RECALIBRATE_TRIGGER:.0%}. "
            f"Orange threshold lowered to {thresholds['orange_min']}."
        )
        if verbose:
            print(f"  [calibrate] WARNING: LOEO DR={loeo_dr:.1%} < trigger — "
                  f"recalibrating Orange threshold -> {thresholds['orange_min']}")
    else:
        threshold_note = (
            f"LOEO DR={loeo_dr:.1%} >= {_DETECTION_RATE_RECALIBRATE_TRIGGER:.0%}. "
            "Baseline SRS §10.4 thresholds retained unchanged."
        )
        if verbose:
            print(f"  [calibrate] LOEO DR={loeo_dr:.1%} OK — "
                  "thresholds unchanged from SRS §10.4 baseline")

    # ── FS band penalty stats ─────────────────────────────────────────────────
    fs_stats = _fit_fs_band_penalty_stats(SAMPLES_PATH)
    if verbose:
        print(f"  [calibrate] FS penalty stats: mean={fs_stats.get('penalty_mean')}, "
              f"p90={fs_stats.get('penalty_p90')}")

    # ── C_cal summary ─────────────────────────────────────────────────────────
    if verbose:
        print(f"  [calibrate] C_cal: empirical={c_cal_empirical:.3f} "
              f"(replaces placeholder {c_cal_placeholder:.3f})")

    # ── Assemble frozen panel figures ─────────────────────────────────────────
    calibration: dict[str, Any] = {
        "frozen_date":  datetime.now(timezone.utc).date().isoformat(),
        "freeze_note":  (
            "These figures are frozen. The validation panel reads them once at "
            "startup and NEVER recomputes them live (SRS §11 / Migration Plan §6)."
        ),

        # LOEO
        "loeo": {
            "n_events":       loeo_n,
            "detection_rate": loeo_dr,
            "timing_error":   loeo_timing,
            "leakage_buffer_days": loeo.get("leakage_buffer_days", 7),
            "run_timestamp_utc": loeo.get("run_timestamp_utc"),
        },

        # LORO
        "loro": {
            "n_regions_total":   loro.get("loro_n_regions_total"),
            "n_regions_scored":  loro.get("loro_n_regions_scored"),
            "detection_rate":    loro_dr,
            "fp_rate":           loro.get("false_positive_rate_aggregate"),
            "c_cal_empirical":   c_cal_empirical,
            "c_cal_placeholder": c_cal_placeholder,
            "c_cal_note":        loro_c_cal.get("c_cal_note", ""),
            "run_timestamp_utc": loro.get("run_timestamp_utc"),
        },

        # Spatial block
        "spatial_block": {
            "mean_detection_rate": spblk_dr,
            "cluster_method":      spblk_method,
            "n_clusters":          spblk.get("spatial_block_n_clusters"),
            "n_scored":            spblk.get("spatial_block_n_scored"),
            "run_timestamp_utc":   spblk.get("run_timestamp_utc"),
        },

        # Tier thresholds
        "tier_thresholds": {
            "source":      threshold_source,
            "note":        threshold_note,
            "thresholds":  thresholds,
        },

        # Confidence factors
        "confidence_factors": {
            "c_cal_calibrated_regions":   c_cal_empirical,
            "c_cal_uncalibrated_regions": c_cal_placeholder,
            "fs_band_penalty_stats":      fs_stats,
            "confidence_formula":
                "confidence_score = 100 * P_class * (1 - FS_band_penalty) * C_cal",
        },

        "produced_by": "ml/validation/calibrate_thresholds.py",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, default=str)

    if verbose:
        print(f"\n[calibrate] Frozen calibration -> {CALIB_PATH}")
        print("=" * 72)

    return calibration


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Phase 6: Recalibrate tier thresholds and freeze panel figures."
    )
    parser.add_argument("--force", action="store_true",
                        help="Recompute even if frozen figures are up-to-date")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = compute_calibration(force=args.force, verbose=not args.quiet)
    print(f"\nFrozen date:     {result['frozen_date']}")
    print(f"LOEO det rate:   {result['loeo']['detection_rate']}")
    print(f"LORO det rate:   {result['loro']['detection_rate']}")
    print(f"C_cal empirical: {result['confidence_factors']['c_cal_calibrated_regions']}")
    print(f"Thresholds:      {result['tier_thresholds']['source']}")
