"""
ml/validation/loro.py
Leave-One-Region-Out (LORO) Validation Harness.

Reference: HydraSense_Final.md §16.3 / §11.3

LOEO (existing: ml/validation/loeo.py) validates within the same region —
it leaves out one *event* from a single event cluster.
LORO validates *geographic generalization* — it trains on all regions except one
and measures whether the model fires correctly for the held-out region.
LORO is the primary evidence that "the system is not just Wayanad with extra steps."

Stage 4 new outputs (served by GET /validation/loro):
  data/validation/loro_results.json   — per-region fold results
  data/validation/loro_summary.json   — aggregate: detection rate, FP rate, C_cal calibration

C_cal calibration (Final.md §11.3):
  The placeholder C_cal=0.75 for uncalibrated regions is replaced by an
  empirically derived value from LORO:
    C_cal_loro = detection_rate_uncalibrated / detection_rate_calibrated
  This is written back to data/validation/loro_summary.json and used by
  the confidence score at inference time when loaded via get_c_cal_for_region().

Fold unit: REGION (10 folds, one per entry in ALL_REGIONS pipeline.py).
Held-out region samples: all events whose region tag matches held-out region_code.
Training set: all samples whose region tag is NOT the held-out region_code.
Leakage prevention: no samples from held-out region in training data (strict boundary).

Detection semantics:
  Same as LOEO: model predicts Orange or Red on a snapshot whose ground-truth
  label is also Orange/Red (within the true alarm window).

Output keys per fold:
  region_code, region_label, n_train_samples, n_test_samples,
  n_events, n_detected, detection_rate, n_negative_samples, n_fp,
  false_positive_rate, timing_errors_min (list), has_local_calibration,
  c_cal_used (placeholder or empirical), notes

IMPORTANT — data reality notice:
  At the time of Stage 4, only the Wayanad event rows in event_centered_samples.parquet
  have a reliable 'region' tag. The multiregion samples have a 'target_location' field
  which is mapped to a region_code via the REGION_LABEL_MAP below.
  For regions with no matched samples, the fold reports n_test_samples=0 and is skipped.
  This is reported honestly in the summary, NOT padded.
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)

from ml.models.train_fusion_model import (
    FusionModel,
    prepare_feature_matrix,
    ALL_FEATURE_COLS,
    INT_TO_TIER,
    TIER_TO_INT,
    join_dynamic_features,
)
from backend.onboarding.pipeline import ALL_REGIONS

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SAMPLES_PATH   = ROOT / "data" / "events"      / "event_centered_samples.parquet"
MULTI_SAMPLES  = ROOT / "data" / "multiregion" / "model_ready" / "event_centered_samples_multiregion.parquet"
RESULTS_DIR    = ROOT / "data" / "validation"
RESULTS_PATH   = RESULTS_DIR / "loro_results.json"
SUMMARY_PATH   = RESULTS_DIR / "loro_summary.json"

# C_cal placeholder (Final.md §11.3 — to be replaced by empirical value post-LORO)
C_CAL_PLACEHOLDER_UNCALIBRATED = 0.75

DETECTION_TIERS = {"Orange", "Red"}

# ---------------------------------------------------------------------------
# Map from historical event labels → region_code
# Covers all naming variants in historical_events.csv + multiregion parquet
# ---------------------------------------------------------------------------
REGION_LABEL_MAP: dict[str, str] = {
    # Wayanad — all known village names from event_centered_samples.parquet
    "wayanad":              "wayanad-kl",
    "mundakkai":            "wayanad-kl",
    "chooralmala":          "wayanad-kl",
    "attamala":             "wayanad-kl",
    "punjirimattom":        "wayanad-kl",   # was missing — 1572 untagged rows
    "wayanad kerala":       "wayanad-kl",
    "mepaddi":              "wayanad-kl",
    "noolpuzha":            "wayanad-kl",
    "meppadi":              "wayanad-kl",
    # Idukki
    "idukki":               "idukki-kl",
    "munnar":               "idukki-kl",
    "idukki kerala":        "idukki-kl",
    "idamalayar":           "idukki-kl",
    # Nilgiris
    "nilgiris":             "nilgiris-tn",
    "ooty":                 "nilgiris-tn",
    "nilgiris tamil nadu":  "nilgiris-tn",
    "gudalur":              "nilgiris-tn",
    # Rudraprayag
    "rudraprayag":          "rudraprayag-uk",
    "kedarnath":            "rudraprayag-uk",
    "ukhimath":             "rudraprayag-uk",
    # Chamoli
    "chamoli":              "chamoli-uk",
    "gopeshwar":            "chamoli-uk",
    "joshimath":            "chamoli-uk",
    "karnaprayag":          "chamoli-uk",
    # Kullu
    "kullu":                "kullu-hp",
    "manali":               "kullu-hp",
    "bhuntar":              "kullu-hp",
    # Mangan / Sikkim
    "mangan":               "mangan-sk",
    "sikkim":               "mangan-sk",
    "north sikkim":         "mangan-sk",
    "lachen":               "mangan-sk",
    "chungthang":           "mangan-sk",
    # Darjeeling
    "darjeeling":           "darjeeling-wb",
    "kalimpong":            "darjeeling-wb",
    "melli":                "darjeeling-wb",
    "kurseong":             "darjeeling-wb",
    # Ribhoi
    "ribhoi":               "ribhoi-ml",
    "nongpoh":              "ribhoi-ml",
    "byrnihat":             "ribhoi-ml",
    # Dhemaji
    "dhemaji":              "dhemaji-as",
    "dibrugarh":            "dhemaji-as",
    "jonai":                "dhemaji-as",
}

# Which regions have GSI calibration (duplicates history_check.KNOWN_CALIBRATED_DISTRICTS)
CALIBRATED_REGIONS = {
    "wayanad-kl", "idukki-kl", "nilgiris-tn",
    "rudraprayag-uk", "chamoli-uk", "kullu-hp",
    "mangan-sk", "darjeeling-wb",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_region_code(row: pd.Series) -> str:
    """
    Determine region_code for a sample row from any naming convention.
    Checks 'region_code', 'region', 'target_location', 'village' columns.
    Returns '' if no match found.
    """
    for col in ("region_code", "region", "target_location", "village"):
        val = str(row.get(col, "") or "").lower().strip()
        if not val:
            continue
        # Direct match
        if val in REGION_LABEL_MAP:
            return REGION_LABEL_MAP[val]
        # Substring match
        for label, code in REGION_LABEL_MAP.items():
            if label in val or val in label:
                return code
    return ""


def load_pooled_samples() -> pd.DataFrame:
    """
    Load all available event-centered samples and tag each with region_code.
    Combines:
      1. data/events/event_centered_samples.parquet (Wayanad-centric)
      2. data/multiregion/model_ready/event_centered_samples_multiregion.parquet
    """
    frames = []

    if SAMPLES_PATH.exists():
        df1 = pd.read_parquet(SAMPLES_PATH)
        df1["_source"] = "wayanad"
        frames.append(df1)
        print(f"[loro] Wayanad samples: {len(df1)} rows")

    if MULTI_SAMPLES.exists():
        df2 = pd.read_parquet(MULTI_SAMPLES)
        df2["_source"] = "multiregion"
        frames.append(df2)
        print(f"[loro] Multiregion samples: {len(df2)} rows")

    if not frames:
        raise FileNotFoundError(
            f"No sample parquets found at:\n  {SAMPLES_PATH}\n  {MULTI_SAMPLES}\n"
            "Run: python ml/features/event_centered_sampling.py"
        )

    df = pd.concat(frames, ignore_index=True)

    # Tag each row with its region_code
    df["region_code"] = df.apply(_map_region_code, axis=1)
    tagged_n = (df["region_code"] != "").sum()
    print(f"[loro] Total pooled samples: {len(df)} ({tagged_n} tagged with region_code)")

    if "snapshot_timestamp" in df.columns:
        df["snapshot_timestamp"] = pd.to_datetime(
            df["snapshot_timestamp"], utc=True, errors="coerce"
        )
    return df


def retrain_without_region(df_all: pd.DataFrame, held_out_code: str) -> FusionModel | None:
    """Train on all rows EXCEPT those from the held-out region."""
    df_train = df_all[df_all["region_code"] != held_out_code].copy()
    if len(df_train) < 20 or (
        "tier_int" in df_train.columns and df_train["tier_int"].nunique() < 2
    ):
        return None
    try:
        df_train = join_dynamic_features(df_train)
    except Exception as exc:
        print(f"    [loro] WARNING: join_dynamic_features failed: {exc}")
    try:
        X, y = prepare_feature_matrix(df_train)
    except Exception as exc:
        print(f"    [loro] WARNING: prepare_feature_matrix failed: {exc}")
        return None
    if X.shape[0] < 20 or y.nunique() < 2:
        return None
    model = FusionModel()
    model.fit(X, y)
    return model


def _score_samples(model: FusionModel, df_test: pd.DataFrame) -> dict[str, Any]:
    """
    Score all held-out region samples and compute detection rate + FP rate.

    Returns:
      n_events, n_detected, detection_rate,
      n_negative_samples, n_fp, false_positive_rate,
      timing_errors_min (list of floats, one per detected event)
    """
    if df_test.empty:
        return {
            "n_events": 0, "n_detected": 0, "detection_rate": 0.0,
            "n_negative_samples": 0, "n_fp": 0, "false_positive_rate": None,
            "timing_errors_min": [],
        }

    try:
        df_test = join_dynamic_features(df_test)
    except Exception:
        pass

    # Group by event_id (or by date+village if no event_id)
    if "event_id" in df_test.columns:
        event_groups = df_test[df_test["event_id"].notna()].groupby("event_id")
    else:
        event_groups = []

    n_events = n_detected = 0
    timing_errors = []

    for event_id, ev_df in event_groups:
        ev_df = ev_df.sort_values("snapshot_timestamp") if "snapshot_timestamp" in ev_df.columns else ev_df
        n_events += 1
        detected = False
        first_alarm_ts = None
        event_ts = None

        # Find event_time
        if "snapshot_timestamp" in ev_df.columns:
            alarm_rows = ev_df[ev_df.get("tier_int", pd.Series(dtype=int)) >= 2] if "tier_int" in ev_df.columns else pd.DataFrame()
            if not alarm_rows.empty:
                first_alarm_ts = alarm_rows["snapshot_timestamp"].min()
            event_ts = ev_df["snapshot_timestamp"].max()

        for _, row in ev_df.iterrows():
            if "tier_int" in row and row["tier_int"] < 2:
                continue   # only score alarm-window rows
            feat_dict = {col: row.get(col) for col in ALL_FEATURE_COLS}
            try:
                pred = model.predict_one(feat_dict)
                if pred.get("tier") in DETECTION_TIERS:
                    detected = True
                    break
            except Exception:
                continue

        if detected:
            n_detected += 1
            if first_alarm_ts is not None and event_ts is not None:
                delta_min = (event_ts - first_alarm_ts).total_seconds() / 60
                if delta_min is not None and not (isinstance(delta_min, float) and (np.isnan(delta_min) or np.isinf(delta_min))):
                    timing_errors.append(round(float(delta_min), 1))

    detection_rate = round(n_detected / n_events, 4) if n_events > 0 else 0.0

    # FP rate on negative (Green) samples in this region
    neg_df = df_test[df_test.get("tier_int", pd.Series(dtype=int)) == 0] if "tier_int" in df_test.columns else pd.DataFrame()
    n_fp = 0
    n_neg = len(neg_df)
    for _, row in neg_df.iterrows():
        feat_dict = {col: row.get(col) for col in ALL_FEATURE_COLS}
        try:
            pred = model.predict_one(feat_dict)
            if pred.get("tier") in DETECTION_TIERS:
                n_fp += 1
        except Exception:
            continue

    fp_rate = round(n_fp / n_neg, 4) if n_neg > 0 else None

    return {
        "n_events":             n_events,
        "n_detected":           n_detected,
        "detection_rate":       detection_rate,
        "n_negative_samples":   n_neg,
        "n_fp":                 n_fp,
        "false_positive_rate":  fp_rate,
        "timing_errors_min":    timing_errors,
    }


# ---------------------------------------------------------------------------
# C_cal empirical calibration
# ---------------------------------------------------------------------------

def calibrate_c_cal(results: list[dict]) -> dict:
    """
    Empirically derive C_cal for uncalibrated regions from LORO fold results.

    Method (Final.md §11.3):
      C_cal_empirical = mean detection_rate(uncalibrated) / mean detection_rate(calibrated)
      Clipped to [0.50, 1.0] — never let C_cal inflate above the calibrated level.

    Returns dict:
      {
        "c_cal_calibrated_mean_detection_rate": float,
        "c_cal_uncalibrated_mean_detection_rate": float,
        "c_cal_empirical": float,
        "c_cal_placeholder": float,
        "c_cal_note": str,
      }
    """
    cal_rates   = [r["detection_rate"] for r in results if r.get("has_local_calibration") and r["n_events"] > 0]
    uncal_rates = [r["detection_rate"] for r in results if not r.get("has_local_calibration") and r["n_events"] > 0]

    cal_mean   = float(np.mean(cal_rates))   if cal_rates   else None
    uncal_mean = float(np.mean(uncal_rates)) if uncal_rates else None

    if cal_mean and uncal_mean and cal_mean > 0:
        c_cal_empirical = round(float(np.clip(uncal_mean / cal_mean, 0.50, 1.0)), 4)
        note = (
            f"Empirical C_cal={c_cal_empirical:.3f} from LORO. "
            f"Calibrated regions: {cal_mean:.1%} detection rate. "
            f"Uncalibrated regions: {uncal_mean:.1%} detection rate. "
            f"Replaces placeholder C_cal={C_CAL_PLACEHOLDER_UNCALIBRATED:.2f}."
        )
    else:
        c_cal_empirical = C_CAL_PLACEHOLDER_UNCALIBRATED
        note = (
            "Insufficient LORO data to derive empirical C_cal "
            f"(cal_folds={len(cal_rates)}, uncal_folds={len(uncal_rates)}). "
            f"Using placeholder C_cal={C_CAL_PLACEHOLDER_UNCALIBRATED}."
        )

    return {
        "c_cal_calibrated_mean_detection_rate":   cal_mean,
        "c_cal_uncalibrated_mean_detection_rate": uncal_mean,
        "c_cal_empirical":    c_cal_empirical,
        "c_cal_placeholder":  C_CAL_PLACEHOLDER_UNCALIBRATED,
        "c_cal_note":         note,
    }


# ---------------------------------------------------------------------------
# Main LORO loop
# ---------------------------------------------------------------------------

def run_loro(
    results_path: Path = RESULTS_PATH,
    summary_path: Path = SUMMARY_PATH,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    Run full LORO validation. Returns aggregate summary.
    Writes loro_results.json + loro_summary.json for the API to serve.
    """
    print("=" * 72)
    print("Stage 4 — Leave-One-Region-Out (LORO) Validation")
    print("Reference: HydraSense_Final.md §16.3 / §11.3")
    print("=" * 72)

    df_all = load_pooled_samples()
    n_regions = len(ALL_REGIONS)
    print(f"\n[loro] {n_regions} regions to hold out (one fold per region)")
    print(f"[loro] Total sample pool: {len(df_all)} rows\n")

    results: list[dict] = []

    for fold_idx, region_def in enumerate(ALL_REGIONS, 1):
        rc    = region_def["region_code"]
        label = region_def["label"]
        is_cal = rc in CALIBRATED_REGIONS

        print(f"  [{fold_idx:02d}/{n_regions}] Hold-out: {rc} ({label})")

        df_test = df_all[df_all["region_code"] == rc].copy()
        n_test  = len(df_test)

        if n_test == 0:
            msg = "No samples found for this region in pooled parquet — fold skipped"
            print(f"         SKIP — {msg}")
            results.append({
                "region_code":          rc,
                "region_label":         label,
                "fold":                 fold_idx,
                "has_local_calibration": is_cal,
                "n_train_samples":      len(df_all) - n_test,
                "n_test_samples":       0,
                "n_events":             0,
                "n_detected":           0,
                "detection_rate":       None,
                "n_negative_samples":   0,
                "n_fp":                 0,
                "false_positive_rate":  None,
                "timing_errors_min":    [],
                "notes":                msg,
            })
            continue

        print(f"         test_samples={n_test}  "
              f"train_samples={len(df_all) - n_test}  "
              f"calibrated={is_cal}")

        model = retrain_without_region(df_all, rc)
        if model is None:
            msg = "Insufficient training data after region exclusion — fold skipped"
            print(f"         SKIP — {msg}")
            results.append({
                "region_code": rc, "region_label": label, "fold": fold_idx,
                "has_local_calibration": is_cal,
                "n_train_samples": len(df_all) - n_test, "n_test_samples": n_test,
                "n_events": 0, "n_detected": 0, "detection_rate": None,
                "n_negative_samples": 0, "n_fp": 0, "false_positive_rate": None,
                "timing_errors_min": [], "notes": msg,
            })
            continue

        scored = _score_samples(model, df_test)

        if verbose:
            if scored["n_events"] > 0:
                print("         -> detected %d/%d events (%.1f%%)" % (
                    scored['n_detected'], scored['n_events'],
                    scored['detection_rate'] * 100))
                if scored["false_positive_rate"] is not None:
                    print("         -> FP rate: %.1f%% (%d/%d negatives)" % (
                        scored['false_positive_rate'] * 100,
                        scored['n_fp'], scored['n_negative_samples']))
                if scored["timing_errors_min"]:
                    median_t = float(np.median(scored["timing_errors_min"]))
                    print("         -> median lead time: %.0f min" % median_t)
            else:
                print("         -> no event rows found in test set")

        results.append({
            "region_code":          rc,
            "region_label":         label,
            "fold":                 fold_idx,
            "has_local_calibration": is_cal,
            "n_train_samples":      len(df_all) - n_test,
            "n_test_samples":       n_test,
            **scored,
            "notes":                "",
        })

    # ---------------------------------------------------------------------------
    # C_cal empirical calibration
    # ---------------------------------------------------------------------------
    c_cal_result = calibrate_c_cal(results)

    # ---------------------------------------------------------------------------
    # Aggregate
    # ---------------------------------------------------------------------------
    scored_folds    = [r for r in results if r["detection_rate"] is not None]
    n_scored        = len(scored_folds)
    n_total_events  = sum(r["n_events"]   for r in scored_folds)
    n_total_detected= sum(r["n_detected"] for r in scored_folds)
    agg_det_rate    = round(n_total_detected / n_total_events, 4) if n_total_events > 0 else 0.0

    all_timings     = [t for r in scored_folds for t in (r["timing_errors_min"] or [])]
    timing_summary  = {}
    if all_timings:
        timing_summary = {
            "mean_min":   round(float(np.mean(all_timings)),   1),
            "median_min": round(float(np.median(all_timings)), 1),
            "min_min":    round(float(np.min(all_timings)),    1),
            "max_min":    round(float(np.max(all_timings)),    1),
            "n":          len(all_timings),
        }

    n_total_fp     = sum(r.get("n_fp", 0) for r in scored_folds)
    n_total_neg    = sum(r.get("n_negative_samples", 0) for r in scored_folds)
    agg_fp_rate    = round(n_total_fp / n_total_neg, 4) if n_total_neg > 0 else None

    # Worst-case: lowest detection rate folds with samples
    worst_folds = sorted(
        [r for r in scored_folds if r["n_events"] > 0],
        key=lambda r: r["detection_rate"],
    )[:3]

    summary = {
        "loro_n_regions_total":     n_regions,
        "loro_n_regions_scored":    n_scored,
        "loro_n_regions_skipped":   n_regions - n_scored,
        "loro_n_events_total":      n_total_events,
        "loro_n_events_detected":   n_total_detected,
        "detection_rate_aggregate": agg_det_rate,
        "false_positive_rate_aggregate": agg_fp_rate,
        "timing_error": timing_summary,
        "c_cal_calibration": c_cal_result,
        "worst_3_regions_by_detection": [
            {
                "region_code": r["region_code"],
                "region_label": r["region_label"],
                "detection_rate": r["detection_rate"],
                "n_events": r["n_events"],
                "has_local_calibration": r["has_local_calibration"],
            }
            for r in worst_folds
        ],
        "methodology_note": (
            "LORO: fold unit = REGION. Model trained on 9 regions, tested on 1. "
            "Repeated for all 10 regions. "
            "Detection = model predicts Orange/Red on a snapshot whose ground-truth "
            "label is also Orange/Red (corrected LOEO semantics). "
            "Regions with 0 test samples are skipped and reported honestly. "
            "C_cal_empirical derived from ratio of uncalibrated to calibrated "
            "detection rates (Final.md §11.3)."
        ),
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    # ---------------------------------------------------------------------------
    # Print summary
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("Stage 4 -- LORO Aggregate Results")
    print("=" * 72)
    print("  Regions scored:   %d/%d" % (n_scored, n_regions))
    print("  Events detected:  %d/%d (%.1f%%)" % (
        n_total_detected, n_total_events, agg_det_rate * 100))
    if agg_fp_rate is not None:
        print("  FP rate:          %.1f%% (%d/%d negatives)" % (
            agg_fp_rate * 100, n_total_fp, n_total_neg))
    if timing_summary:
        print("  Lead time (median): %.0f min  range [%.0f, %.0f] min" % (
            timing_summary['median_min'],
            timing_summary['min_min'],
            timing_summary['max_min']))
    print()
    print("  C_cal calibration:")
    print("    Placeholder:  %s" % c_cal_result['c_cal_placeholder'])
    print("    Empirical:    %s" % c_cal_result['c_cal_empirical'])
    print("    Note:         %s" % c_cal_result['c_cal_note'][:100])
    if worst_folds:
        print("\n  Weakest 3 regions (lowest detection rate):")
        for r in worst_folds:
            cal = "calibrated" if r["has_local_calibration"] else "uncalibrated"
            print("    %-22s %.1f%%  (%d events, %s)" % (
                r['region_code'], r['detection_rate'] * 100,
                r['n_events'], cal))
    print("=" * 72)

    # ---------------------------------------------------------------------------
    # Write outputs
    # ---------------------------------------------------------------------------
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    def _clean_nans(obj):
        if isinstance(obj, float):
            if np.isnan(obj) or np.isinf(obj):
                return None
            return obj
        elif isinstance(obj, dict):
            return {k: _clean_nans(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_clean_nans(v) for v in obj]
        return obj

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(_clean_nans(results), f, indent=2, default=str)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(_clean_nans(summary), f, indent=2, default=str)

    print("\n[loro] Per-region results -> %s" % results_path)
    print("[loro] Summary           -> %s" % summary_path)
    return summary


# ---------------------------------------------------------------------------
# C_cal runtime accessor — used by confidence score at inference time
# ---------------------------------------------------------------------------

def get_c_cal_for_region(region_code: str) -> float:
    """
    Return the empirical C_cal for a given region from LORO results.
    Falls back to the placeholder if LORO hasn't been run or the region
    is calibrated (C_cal=1.0 for calibrated regions always).

    Called by compute_confidence_score() at inference time.
    """
    if region_code in CALIBRATED_REGIONS:
        return 1.0  # calibrated regions always get C_cal=1.0

    if not SUMMARY_PATH.exists():
        return C_CAL_PLACEHOLDER_UNCALIBRATED

    try:
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        c_cal_result = summary.get("c_cal_calibration", {})
        empirical = c_cal_result.get("c_cal_empirical")
        if empirical is not None:
            return float(empirical)
    except Exception:
        pass

    return C_CAL_PLACEHOLDER_UNCALIBRATED


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="HydraSense Stage 4 — LORO validation (Final.md §16.3)"
    )
    parser.add_argument("--quiet",       action="store_true", help="Suppress per-fold output")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR,
                        help="Output directory for JSON results")
    args = parser.parse_args()

    run_loro(
        results_path=args.results_dir / "loro_results.json",
        summary_path=args.results_dir / "loro_summary.json",
        verbose=not args.quiet,
    )
