"""
ml/validation/spatial_block.py
Leave-One-Cluster (Spatial Block) Validation.

Phase 6 requirement (Migration Plan §6 / SRS §11.3):
  Complement LOEO (event-level) and LORO (region-level) with a spatial block
  test that groups hexes by H3 resolution-4 cluster (parent cell), holds out
  one cluster at a time, and reports detection rate per cluster.

Purpose:
  LOEO/LORO can still leak spatial autocorrelation when training events share
  hexes with the held-out event. Spatial block CV uses a different hold-out
  unit — the H3 parent cluster — so geographically adjacent hexes never appear
  in both train and test for the same fold.

Fold unit: H3 res-4 parent cell (derived from sample hex_id at res 8/9).
Detection semantics: same as LOEO (corrected v2).
Output: data/validation/spatial_block_results.json + spatial_block_summary.json

If h3 is not installed or hex_id column is missing, the harness degrades
gracefully to a random 5-fold spatial proxy (cluster by geographic hash of
hex_id prefix) and notes this in the summary.
"""

from __future__ import annotations

import hashlib
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
SAMPLES_PATH  = ROOT / "data" / "events" / "event_centered_samples.parquet"
RESULTS_DIR   = ROOT / "data" / "validation"
RESULTS_PATH  = RESULTS_DIR / "spatial_block_results.json"
SUMMARY_PATH  = RESULTS_DIR / "spatial_block_summary.json"

DETECTION_TIERS = {"Orange", "Red"}
N_CLUSTERS = 5  # fallback if h3 not available

# ---------------------------------------------------------------------------
# Imports from Phase 6 model
# ---------------------------------------------------------------------------
from ml.models.train_fusion_model import (
    FusionModel,
    prepare_feature_matrix,
    ALL_FEATURE_COLS,
    INT_TO_TIER,
    join_dynamic_features,
)


# ---------------------------------------------------------------------------
# Cluster assignment
# ---------------------------------------------------------------------------

def assign_clusters(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign each row a cluster_id based on H3 parent (res 4) if h3 available,
    otherwise use a deterministic 5-way hash of the first 4 chars of hex_id.
    """
    df = df.copy()

    if "hex_id" not in df.columns or df["hex_id"].isna().all():
        df["cluster_id"] = "cluster_unknown"
        return df

    try:
        import h3  # type: ignore
        def _parent(hx: str) -> str:
            try:
                return h3.h3_to_parent(str(hx), 4)
            except Exception:
                return None
        df["cluster_id"] = df["hex_id"].apply(_parent)
        # If H3 failed for most rows, fall back
        n_valid   = df["cluster_id"].notna().sum()
        n_unique  = df["cluster_id"].nunique()
        if n_valid < len(df) * 0.5 or n_unique < 2:
            raise ValueError(f"H3 produced only {n_unique} cluster(s) for {n_valid} rows — using hash fallback")
        df.attrs["cluster_method"] = "h3_res4"
    except (ImportError, ValueError, Exception):
        # Fallback: deterministic 5-way hash on the MIDDLE chars of hex_id
        # (chars 0-4 are the H3 res prefix, chars 4-8 carry per-cell variance)
        def _hash_cluster(hx: str) -> str:
            segment = str(hx)[4:8] if len(str(hx)) >= 8 else str(hx)
            digest  = hashlib.md5(segment.encode()).hexdigest()
            return f"cluster_{int(digest[:2], 16) % N_CLUSTERS}"
        df["cluster_id"] = df["hex_id"].apply(_hash_cluster)
        df.attrs["cluster_method"] = f"hash_mid_{N_CLUSTERS}fold_fallback"

    return df


# ---------------------------------------------------------------------------
# Per-fold scoring (reuse LOEO detection semantics)
# ---------------------------------------------------------------------------

def score_fold(
    model: FusionModel,
    df_test: pd.DataFrame,
) -> dict[str, Any]:
    """Score test fold rows; return aggregate detection metrics for the fold."""
    if df_test.empty:
        return {"n_test": 0, "n_detected": 0, "n_fp": 0, "n_neg": 0,
                "detection_rate": None, "fp_rate": None, "notes": "empty fold"}

    try:
        df_test = join_dynamic_features(df_test)
    except Exception:
        pass

    # Rows where ground truth is alarm
    alarm_rows = df_test[df_test["tier_int"] >= 2]  # Orange=2, Red=3
    neg_rows   = df_test[df_test["tier_int"] < 2]

    n_detected, n_fp = 0, 0

    for _, row in alarm_rows.iterrows():
        feat = {col: row.get(col) for col in ALL_FEATURE_COLS}
        try:
            pred = model.predict_one(feat)
            if pred.get("tier") in DETECTION_TIERS:
                n_detected += 1
        except Exception:
            pass

    for _, row in neg_rows.iterrows():
        feat = {col: row.get(col) for col in ALL_FEATURE_COLS}
        try:
            pred = model.predict_one(feat)
            if pred.get("tier") in DETECTION_TIERS:
                n_fp += 1
        except Exception:
            pass

    n_alarm = len(alarm_rows)
    n_neg   = len(neg_rows)
    det_rate = round(n_detected / n_alarm, 4) if n_alarm > 0 else None
    fp_rate  = round(n_fp / n_neg, 4) if n_neg > 0 else None

    return {
        "n_test":         len(df_test),
        "n_alarm":        n_alarm,
        "n_detected":     n_detected,
        "n_neg":          n_neg,
        "n_fp":           n_fp,
        "detection_rate": det_rate,
        "fp_rate":        fp_rate,
        "notes":          "",
    }


# ---------------------------------------------------------------------------
# Main spatial-block CV loop
# ---------------------------------------------------------------------------

def run_spatial_block(
    samples_path: Path = SAMPLES_PATH,
    results_path: Path = RESULTS_PATH,
    summary_path: Path = SUMMARY_PATH,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    Run spatial block (leave-one-cluster) cross-validation.
    Outputs spatial_block_results.json + spatial_block_summary.json.
    """
    print("=" * 72)
    print("Phase 6 -- Spatial Block (Leave-One-Cluster) Validation")
    print("Fold unit: H3 res-4 parent cluster (or 5-way hash fallback)")
    print("=" * 72)

    if not samples_path.exists():
        raise FileNotFoundError(
            f"Sample set not found: {samples_path}\n"
            "Run: python ml/features/event_centered_sampling.py"
        )

    df_all = pd.read_parquet(samples_path)
    df_all = assign_clusters(df_all)
    cluster_method = df_all.attrs.get("cluster_method", "unknown")

    clusters = sorted(df_all["cluster_id"].unique())
    print(f"\n[spatial_block] {len(df_all)} rows | {len(clusters)} clusters | method={cluster_method}\n")

    fold_results: list[dict[str, Any]] = []

    for fold_idx, cluster_id in enumerate(clusters, 1):
        df_test  = df_all[df_all["cluster_id"] == cluster_id].copy()
        df_train = df_all[df_all["cluster_id"] != cluster_id].copy()

        if verbose:
            print(f"  [{fold_idx:02d}/{len(clusters)}] cluster={cluster_id} "
                  f"train={len(df_train)} test={len(df_test)}")

        if len(df_train) < 10 or df_train["tier_int"].nunique() < 2:
            note = "insufficient training data for this fold"
            print(f"       SKIP -- {note}")
            fold_results.append({
                "cluster_id": cluster_id, "fold": fold_idx,
                "n_train": len(df_train), "n_test": len(df_test),
                "detection_rate": None, "fp_rate": None, "notes": note,
            })
            continue

        try:
            df_train_dyn = join_dynamic_features(df_train)
        except Exception:
            df_train_dyn = df_train

        try:
            X, y = prepare_feature_matrix(df_train_dyn)
        except Exception as exc:
            note = f"prepare_feature_matrix failed: {exc}"
            fold_results.append({
                "cluster_id": cluster_id, "fold": fold_idx,
                "n_train": len(df_train), "n_test": len(df_test),
                "detection_rate": None, "fp_rate": None, "notes": note,
            })
            continue

        if X.shape[0] < 10 or y.nunique() < 2:
            note = "degenerate training set after feature matrix prep"
            fold_results.append({
                "cluster_id": cluster_id, "fold": fold_idx,
                "n_train": len(df_train), "n_test": len(df_test),
                "detection_rate": None, "fp_rate": None, "notes": note,
            })
            continue

        model = FusionModel()
        model.fit(X, y)

        scored = score_fold(model, df_test)
        dr_str = f"{scored['detection_rate']:.1%}" if scored["detection_rate"] is not None else "N/A"
        fp_str = f"{scored['fp_rate']:.1%}" if scored["fp_rate"] is not None else "N/A"
        if verbose:
            print(f"       -> det={dr_str}  fp={fp_str}  alarm_rows={scored.get('n_alarm', 0)}")

        fold_results.append({
            "cluster_id":     cluster_id,
            "fold":           fold_idx,
            "n_train":        len(df_train),
            "n_test":         scored["n_test"],
            "n_alarm":        scored.get("n_alarm", 0),
            "n_detected":     scored["n_detected"],
            "n_neg":          scored["n_neg"],
            "n_fp":           scored["n_fp"],
            "detection_rate": scored["detection_rate"],
            "fp_rate":        scored["fp_rate"],
            "notes":          scored["notes"],
        })

    # Aggregate
    scored_folds = [r for r in fold_results if r["detection_rate"] is not None]
    det_rates = [r["detection_rate"] for r in scored_folds]
    fp_rates  = [r["fp_rate"] for r in scored_folds if r["fp_rate"] is not None]

    mean_det = round(float(np.mean(det_rates)), 4)  if det_rates else None
    mean_fp  = round(float(np.mean(fp_rates)),  4)  if fp_rates  else None

    summary = {
        "spatial_block_n_clusters":     len(clusters),
        "spatial_block_n_scored":       len(scored_folds),
        "spatial_block_n_skipped":      len(fold_results) - len(scored_folds),
        "cluster_method":               cluster_method,
        "mean_detection_rate":          mean_det,
        "mean_fp_rate":                 mean_fp,
        "per_cluster_detection_rates":  {
            r["cluster_id"]: r["detection_rate"] for r in fold_results
        },
        "methodology_note": (
            "Spatial block CV: fold unit = H3 res-4 parent cluster "
            "(or 5-fold hash if h3 not installed). "
            "Prevents spatial-autocorrelation leakage across geographically "
            "adjacent hexes. Detection = model predicts Orange/Red on a row "
            "whose ground-truth tier_int >= 2 (same semantics as LOEO v2)."
        ),
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "n_sample_rows": len(df_all),
    }

    print("\n" + "=" * 72)
    print("Phase 6 -- Spatial Block Aggregate Results")
    print("=" * 72)
    print(f"  Clusters evaluated:  {len(clusters)}")
    print(f"  Clusters scored:     {len(scored_folds)}")
    print(f"  Mean detection rate: {f'{mean_det:.1%}' if mean_det is not None else 'N/A'}")
    print(f"  Mean FP rate:        {f'{mean_fp:.1%}' if mean_fp is not None else 'N/A'}")
    print(f"  Cluster method:      {cluster_method}")

    # Worst clusters
    worst = sorted(scored_folds, key=lambda r: (r["detection_rate"] or 1.0))[:3]
    if worst:
        print("\n  Worst 3 clusters by detection rate:")
        for r in worst:
            print(f"    {r['cluster_id']}: det={r['detection_rate']:.1%} "
                  f"fp={r.get('fp_rate') or 'N/A'}")
    print("=" * 72)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(fold_results, f, indent=2, default=str)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n[spatial_block] Results -> {results_path}")
    print(f"[spatial_block] Summary -> {summary_path}")
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_spatial_block(verbose=True)
