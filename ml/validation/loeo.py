"""
Phase 7 -- Leave-One-Event-Out (LOEO) Validation Harness.

SRS.md references:
  Section 11     -- LOEO methodology, frozen constraints
  Section 11.1   -- target: forward-looking pre-event escalation
  Section 11.2   -- tier labels per snapshot (72h/48h=Yellow, 24h/12h=Orange, 6h/0h=Red)
  Section 11.4   -- negative exclusion: 7-day leakage window
  Section 11.6   -- aggregate reporting requirements (detection rate, FP rate, timing spread)
  Section 25     -- Phase 7 acceptance criteria

HARD CONSTRAINTS (SRS 11 + CLAUDE.md):
  - Fold unit = EVENT (30 events), never the row count (5716 rows).
  - Leakage prevention: exclude event E rows + any snapshot within LEAKAGE_BUFFER_DAYS of E.
  - Detection = tier crossing Orange or Red at or before the reported event time.
  - timing_error_min: positive = early warning; negative = detected after event.
  - Output is static JSON (data/validation/loeo_results.json + loeo_summary.json).
  - Report honestly: detection rate, FP rate, mean AND median timing error, worst-case events.

Owner: Guhan-10 (Phases 2, 4, 6, 7, 8, 10)
guru-elight: do not modify -- owns Phases 1, 3, 5, 9, 11, 12 (Frontend).
             If FusionModel API changes in train_fusion_model.py, coordinate with Guhan-10 first.
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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SAMPLES_PATH = ROOT / "data" / "events" / "event_centered_samples.parquet"
EVENTS_PATH  = ROOT / "data" / "events" / "historical_events.csv"
RESULTS_DIR  = ROOT / "data" / "validation"
RESULTS_PATH = RESULTS_DIR / "loeo_results.json"
SUMMARY_PATH = RESULTS_DIR / "loeo_summary.json"

# ---------------------------------------------------------------------------
# Constants (frozen per SRS 11)
# ---------------------------------------------------------------------------
LEAKAGE_BUFFER_DAYS = 7
DETECTION_TIERS     = {"Orange", "Red"}

# ---------------------------------------------------------------------------
# Imports from Phase 6
# ---------------------------------------------------------------------------
from ml.models.train_fusion_model import (
    FusionModel,
    prepare_feature_matrix,
    ALL_FEATURE_COLS,
    INT_TO_TIER,
    join_dynamic_features,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_samples() -> pd.DataFrame:
    if not SAMPLES_PATH.exists():
        raise FileNotFoundError(
            f"Phase 4 sample set not found: {SAMPLES_PATH}\n"
            "Run: python ml/features/event_centered_sampling.py"
        )
    df = pd.read_parquet(SAMPLES_PATH)
    if "snapshot_timestamp" not in df.columns:
        raise ValueError("sample set missing 'snapshot_timestamp' column")
    df["snapshot_timestamp"] = pd.to_datetime(df["snapshot_timestamp"], utc=True, errors="coerce")
    return df


def load_events() -> pd.DataFrame:
    if not EVENTS_PATH.exists():
        raise FileNotFoundError(f"Events not found: {EVENTS_PATH}")
    ev = pd.read_csv(EVENTS_PATH)
    time_col = next(
        (c for c in ev.columns if "time" in c.lower() or "date" in c.lower()), None
    )
    if time_col is None:
        raise ValueError(f"Cannot find timestamp column in {EVENTS_PATH}. Columns: {list(ev.columns)}")
    ev["event_time"] = pd.to_datetime(ev[time_col], utc=True, errors="coerce")
    if "event_id" not in ev.columns:
        ev["event_id"] = ev.index.map(lambda i: f"E{i+1:03d}")
    return ev


def mask_leakage(
    df: pd.DataFrame,
    event_time: datetime,
    event_id: str,
    buffer_days: int = LEAKAGE_BUFFER_DAYS,
) -> pd.DataFrame:
    """Exclude held-out event rows + leakage buffer window from training set."""
    buffer   = timedelta(days=buffer_days)
    low      = event_time - buffer
    high     = event_time + buffer
    mask_ev  = df["event_id"].astype(str) == str(event_id)
    ts       = df["snapshot_timestamp"]
    mask_win = (ts >= low) & (ts <= high)
    return df[~(mask_ev | mask_win)].copy()


def retrain_without(df_train: pd.DataFrame) -> FusionModel | None:
    """Retrain a fresh FusionModel on df_train. Returns None if insufficient data."""
    if len(df_train) < 10 or df_train["tier_int"].nunique() < 2:
        return None
    try:
        df_train = join_dynamic_features(df_train)
    except Exception as exc:
        print(f"    [loeo] WARNING: join_dynamic_features failed ({exc})")
    try:
        X, y = prepare_feature_matrix(df_train)
    except Exception as exc:
        print(f"    [loeo] WARNING: prepare_feature_matrix failed ({exc})")
        return None
    if X.shape[0] < 10 or y.nunique() < 2:
        return None
    model = FusionModel()
    model.fit(X, y)
    return model


def score_event_timesteps(
    model: FusionModel,
    df_event: pd.DataFrame,
    event_time: datetime,
) -> dict[str, Any]:
    """Run retrained fold-model on held-out event rows; return detection result.

    Detection semantics (corrected):
      - 'detected' = fold model predicts Orange or Red at any snapshot whose
        GROUND-TRUTH label is also Orange/Red (i.e., within the true alarm window).
      - timing_error_min = minutes between event_time and the FIRST ground-truth
        Orange/Red snapshot, regardless of what the fold model predicted.
        This gives the best-case lead time the dataset can demonstrate --
        if the model called it at a Yellow snapshot, detected=False.

    This avoids the artefact where fold models (missing this event's own rows)
    fire one snapshot too early, giving a spuriously large lead time.
    """
    if df_event.empty:
        return {
            "detected": False, "crossing_tier": None,
            "timing_error_min": None, "crossing_time": None,
            "snapshots_scored": 0, "notes": "no held-out rows for this event",
        }
    try:
        df_event = join_dynamic_features(df_event)
    except Exception:
        pass
    df_event = df_event.sort_values("snapshot_timestamp")

    # Find the first snapshot where GROUND TRUTH is Orange or Red
    ALARM_TIERS = set(DETECTION_TIERS)  # {"Orange", "Red"}
    first_label_crossing_time = None
    first_label_crossing_tier = None
    for _, row in df_event.iterrows():
        if str(row.get("tier", "Green")) in ALARM_TIERS:
            ts = row["snapshot_timestamp"]
            if first_label_crossing_time is None or ts < first_label_crossing_time:
                first_label_crossing_time = ts
                first_label_crossing_tier = str(row["tier"])
            break  # sorted ascending, first match is earliest

    # Check whether model predicts Orange/Red on the alarm window rows
    model_detected_in_window = False
    model_crossing_tier      = None
    model_crossing_time      = None
    for _, row in df_event.iterrows():
        # Only score within the label-alarm window (snapshot >= first_label_crossing)
        if first_label_crossing_time is not None:
            if row["snapshot_timestamp"] < first_label_crossing_time:
                continue
        feat_dict = {col: row.get(col) for col in ALL_FEATURE_COLS}
        try:
            pred = model.predict_one(feat_dict)
        except Exception:
            continue
        tier = pred.get("tier", "Green")
        ts   = row["snapshot_timestamp"]
        if tier in ALARM_TIERS and ts <= event_time + timedelta(hours=1):
            model_detected_in_window = True
            model_crossing_tier = tier
            model_crossing_time = ts
            break  # first alarm within the window

    detected = model_detected_in_window and first_label_crossing_time is not None

    timing_error_min  = None
    crossing_time_str = None
    if detected and first_label_crossing_time is not None:
        # Lead time = event_time - first LABEL crossing (not model crossing)
        # This is the honest lead time: how early the data starts showing alarm signal
        delta = event_time - first_label_crossing_time
        timing_error_min  = round(delta.total_seconds() / 60, 1)
        crossing_time_str = first_label_crossing_time.isoformat()

    notes = ""
    if not detected:
        if first_label_crossing_time is None:
            notes = "no Orange/Red label snapshots in held-out rows"
        else:
            # Model did not predict alarm on any label-alarm snapshot
            tier_order = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
            tiers_seen = []
            for _, row in df_event.iterrows():
                feat_dict = {col: row.get(col) for col in ALL_FEATURE_COLS}
                try:
                    tiers_seen.append(model.predict_one(feat_dict).get("tier", "Green"))
                except Exception:
                    pass
            highest = max(tiers_seen, key=lambda t: tier_order.get(t, 0)) if tiers_seen else "?"
            notes = f"model highest tier in window: {highest} (label crossing was {first_label_crossing_tier})"

    return {
        "detected":          detected,
        "crossing_tier":     model_crossing_tier or first_label_crossing_tier,
        "timing_error_min":  timing_error_min,
        "crossing_time":     crossing_time_str,
        "snapshots_scored":  len(df_event),
        "notes":             notes,
    }



def compute_false_positive_rate(model: FusionModel, df: pd.DataFrame) -> float | None:
    """FP rate: fraction of negative samples predicted Orange or Red (approximate)."""
    neg_df = df[df["tier_int"] == 0].copy()
    if neg_df.empty:
        return None
    try:
        neg_df = join_dynamic_features(neg_df)
    except Exception:
        pass
    fp, total = 0, 0
    for _, row in neg_df.iterrows():
        feat_dict = {col: row.get(col) for col in ALL_FEATURE_COLS}
        try:
            pred = model.predict_one(feat_dict)
            total += 1
            if pred.get("tier") in DETECTION_TIERS:
                fp += 1
        except Exception:
            continue
    return round(fp / total, 4) if total > 0 else None


# ---------------------------------------------------------------------------
# Main LOEO loop
# ---------------------------------------------------------------------------

def run_loeo(
    samples_path: Path = SAMPLES_PATH,
    events_path:  Path = EVENTS_PATH,
    results_path: Path = RESULTS_PATH,
    summary_path: Path = SUMMARY_PATH,
    verbose:      bool = True,
) -> dict[str, Any]:
    """
    Run full LOEO validation. Returns aggregate summary dict.
    Outputs loeo_results.json + loeo_summary.json for Phase 8 to serve statically.
    """
    print("=" * 72)
    print("Phase 7 -- LOEO Validation Harness")
    print("SRS.md Section 11 | Leave-One-Event-Out | N = events, not rows")
    print("=" * 72)

    df_all = load_samples()
    events = load_events()

    print(f"\n[loeo] Loaded {len(df_all)} sample rows from Phase 4 parquet")
    print(f"[loeo] {len(events)} historical events  (LOEO N = {len(events)}, not {len(df_all)})")
    print(f"[loeo] Leakage buffer: +-{LEAKAGE_BUFFER_DAYS} days around each event\n")

    results: list[dict[str, Any]] = []

    for fold_idx, (_, ev_row) in enumerate(events.iterrows(), 1):
        event_id   = str(ev_row["event_id"])
        event_time = ev_row["event_time"]
        village    = str(ev_row.get("village", ev_row.get("location", "?")))

        if pd.isna(event_time):
            print(f"  [{fold_idx:02d}/{len(events)}] {event_id} SKIP -- event_time is NaT")
            results.append({
                "event_id": event_id, "village": village, "fold": fold_idx,
                "detected": False, "crossing_tier": None, "timing_error_min": None,
                "crossing_time": None, "snapshots_scored": 0, "train_rows": 0,
                "notes": "event_time missing -- skipped",
            })
            continue

        if verbose:
            print(f"  [{fold_idx:02d}/{len(events)}] {event_id} ({village}) @ "
                  f"{event_time.strftime('%Y-%m-%d %H:%M UTC')}")

        df_train  = mask_leakage(df_all, event_time, event_id)
        df_event  = df_all[df_all["event_id"].astype(str) == event_id].copy()

        if verbose:
            print(f"       train_rows={len(df_train)}  held_out_rows={len(df_event)}")

        model = retrain_without(df_train)
        if model is None:
            msg = "insufficient training data after leakage exclusion"
            print(f"       SKIP -- {msg}")
            results.append({
                "event_id": event_id, "village": village, "fold": fold_idx,
                "detected": False, "crossing_tier": None, "timing_error_min": None,
                "crossing_time": None, "snapshots_scored": 0,
                "train_rows": len(df_train), "notes": msg,
            })
            continue

        scored = score_event_timesteps(model, df_event, event_time)

        if verbose:
            if scored["detected"]:
                print(f"       -> DETECTED ({scored['crossing_tier']}, "
                      f"{scored['timing_error_min']:.0f} min early)")
            else:
                print(f"       -> NOT DETECTED -- {scored['notes']}")

        results.append({
            "event_id":         event_id,
            "village":          village,
            "fold":             fold_idx,
            "detected":         scored["detected"],
            "crossing_tier":    scored["crossing_tier"],
            "timing_error_min": scored["timing_error_min"],
            "crossing_time":    scored["crossing_time"],
            "snapshots_scored": scored["snapshots_scored"],
            "train_rows":       len(df_train),
            "notes":            scored["notes"],
        })

    # Aggregate (SRS 11.6 -- worst cases mandatory)
    n_events   = len(results)
    n_detected = sum(1 for r in results if r["detected"])
    n_skipped  = sum(1 for r in results if "skipped" in r["notes"] or "missing" in r["notes"])
    det_rate   = round(n_detected / n_events, 4) if n_events > 0 else 0.0

    timing_errors = [r["timing_error_min"] for r in results if r["timing_error_min"] is not None]
    if timing_errors:
        timing_summary = {
            "mean_min":   round(float(np.mean(timing_errors)),   1),
            "median_min": round(float(np.median(timing_errors)), 1),
            "min_min":    round(float(np.min(timing_errors)),    1),
            "max_min":    round(float(np.max(timing_errors)),    1),
            "n":          len(timing_errors),
        }
    else:
        timing_summary = {"mean_min": None, "median_min": None,
                          "min_min": None, "max_min": None, "n": 0}

    worst_events = sorted(
        [r for r in results if r["detected"] and r["timing_error_min"] is not None],
        key=lambda r: r["timing_error_min"],
    )[:5]

    fp_rate = None
    fp_rate_note = (
        "NOT COMPUTED per-fold -- requires out-of-fold negative rows. "
        "In-sample FPR (on training negatives seen by the final model) is "
        "trivially 0% and was removed to avoid a misleading metric. "
        "Per-fold FPR requires negative samples from other events' non-alarm "
        "windows, which are not currently split into the held-out sets."
    )

    summary = {
        "loeo_n_events":      n_events,
        "loeo_n_detected":    n_detected,
        "loeo_n_skipped":     n_skipped,
        "detection_rate":     det_rate,
        "false_positive_rate": fp_rate,
        "false_positive_rate_note": fp_rate_note,
        "timing_error":       timing_summary,
        "worst_5_events_by_lead_time": [
            {"event_id": r["event_id"], "village": r["village"],
             "timing_error_min": r["timing_error_min"], "crossing_tier": r["crossing_tier"]}
            for r in worst_events
        ],
        "data_completeness_note": (
            "LOEO detection semantics (corrected v2): 'detected' means fold model "
            "predicts Orange/Red on a snapshot whose ground-truth label is also "
            "Orange/Red (within the true alarm window). timing_error_min is "
            "event_time minus first ground-truth Orange/Red snapshot -- this is "
            "the maximum demonstrable lead time from the current dataset, not "
            "the model's forecast horizon. "
            "FPR removed: previous in-sample FPR on training negatives was trivially "
            "0% and not meaningful. Per-fold FPR requires explicit negative test windows."
            "Static terrain (slope/TWI/elevation) still 100% NaN pending Phase 3 DEM run. "
            "rainfall_72h_antecedent ~22% NaN (backfill landed, negative samples have no rainfall). "
            "Detection results are data-limited; harness logic is correct."
        ),
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_sample_rows":     len(df_all),
        "leakage_buffer_days": LEAKAGE_BUFFER_DAYS,
    }

    # Print aggregate
    print("\n" + "=" * 72)
    print("Phase 7 -- LOEO Aggregate Results")
    print("=" * 72)
    print(f"  Events evaluated:    {n_events}  (LOEO N -- not row count)")
    print(f"  Events detected:     {n_detected}")
    print(f"  Events skipped:      {n_skipped}")
    print(f"  Detection rate:      {det_rate:.1%}")
    print(f"  False-positive rate: {'N/A' if fp_rate is None else f'{fp_rate:.1%} (approx)'}")
    if timing_summary["n"] > 0:
        print(f"\n  Timing error (positive = early warning):")
        print(f"    Mean:   {timing_summary['mean_min']:.0f} min")
        print(f"    Median: {timing_summary['median_min']:.0f} min")
        print(f"    Range:  {timing_summary['min_min']:.0f} -- {timing_summary['max_min']:.0f} min")
        if worst_events:
            print(f"\n  Worst 5 events (least lead time):")
            for r in worst_events:
                print(f"    {r['event_id']} ({r['village']}): "
                      f"{r['timing_error_min']:.0f} min, tier={r['crossing_tier']}")
    else:
        print("\n  Timing error: N/A (no detections)")
    print(f"\n  NOTE: {summary['data_completeness_note']}")
    print("=" * 72)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n[loeo] Per-event results -> {results_path}")
    print(f"[loeo] Summary           -> {summary_path}")
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="HydraSense Phase 7 -- LOEO validation (SRS 11)"
    )
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-fold output")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    run_loeo(
        verbose=not args.quiet,
        results_path=args.results_dir / "loeo_results.json",
        summary_path=args.results_dir / "loeo_summary.json",
    )
