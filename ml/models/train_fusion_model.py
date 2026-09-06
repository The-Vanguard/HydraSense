"""
train_fusion_model.py — XGBoost fusion model training.

Implements: SRS.md Section 10.2 (fusion model), Section 10.3 (confidence score),
            Section 10.4 (tiering), Phase 6 Part 2.
Owner: Dev B (Phase 6)

WHAT THIS DOES
--------------
Trains the XGBoost 4-class classifier that produces risk_score (0-100) per hex
per ingestion cycle, using the enriched training set from Phase 6 Part 1
(dynamic_features.py fills the Phase 4 parquet before this runs).

OUTPUT
------
  ml/models/fusion_model.json          -- XGBoost native format (preferred)
  ml/models/fusion_model_metadata.json -- feature list, thresholds, training stats
                                          (Phase 7 LOEO and Phase 9 lead-time reload from these)

FROZEN FORMULAS (CLAUDE.md + SRS.md -- do not alter)
------------------------------------------------------
risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88
  where P() values come from XGBoost's predict_proba (multi:softprob)

tier thresholds (Section 10.4):
  Green:  0 <= score < 30
  Yellow: 30 <= score < 55
  Orange: 55 <= score < 75
  Red:    75 <= score <= 100

confidence_score = 100 * model_class_probability * (1 - fs_band_width_penalty)
  model_class_probability = XGBoost's probability for the predicted tier
  fs_band_width_penalty from dynamic_features.compute_fs_band_width_penalty()

HARD CONSTRAINTS (CLAUDE.md)
-----------------------------
- XGBoost only. Never implement PSO-BP under any circumstances.
- tier is DERIVED from risk_score -- never predicted separately with argmax.
  (Score and tier must be mutually consistent by construction.)
- antecedent_precipitation_index -- NEVER api_score anywhere in this file.
- Model is saved for Phase 7 (LOEO) and Phase 9 (lead-time) to reload.
- Do not retrain the model on demand (live) -- training is offline, one-time.
"""

import json
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report, confusion_matrix

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parents[2]
DATA_DIR    = REPO_ROOT / "data"
EVENTS_DIR  = DATA_DIR / "events"
MODELS_DIR  = REPO_ROOT / "ml" / "models"

SAMPLES_PARQUET    = EVENTS_DIR / "event_centered_samples.parquet"
MODEL_PATH         = MODELS_DIR / "fusion_model.json"
METADATA_PATH      = MODELS_DIR / "fusion_model_metadata.json"

# ---------------------------------------------------------------------------
# Feature columns going into XGBoost (SRS.md Section 9, 25 features)
# ORDER IS FROZEN -- Phase 7 and Phase 9 reload with this exact list.
# antecedent_precipitation_index -- NEVER api_score (CLAUDE.md / SRS.md Section 9)
# ---------------------------------------------------------------------------
FEATURE_COLUMNS = [
    # Static -- 11 features
    "slope_deg",
    "aspect",
    "TWI",
    "TRI",
    "elevation",
    "distance_to_stream_m",
    "drainage_density",
    "land_use_class",           # ESA WorldCover nominal int; XGBoost categorical
    "ndvi_mean",
    "historical_event_count_500m",
    "gsi_susceptibility_class_int",   # ordinal 0-3 (Low=0, Very High=3)
    # Dynamic -- 14 features
    "rainfall_1h",
    "rainfall_3h",
    "rainfall_6h",
    "rainfall_24h",
    "rainfall_72h_antecedent",
    "rain_intensity_mm_hr",
    "antecedent_precipitation_index",   # NEVER api_score
    "soil_saturation_ratio",            # = GWETROOT directly (SRS.md Section 10.1)
    "factor_of_safety",
    "factor_of_safety_min",
    "factor_of_safety_max",
    "simulated_ffgs_signal",            # SIMULATED proxy
    "simulated_gsi_signal",             # SIMULATED proxy
    "iot_anomaly_flag",
]

TARGET_COLUMN = "tier_int"   # 0=Green, 1=Yellow, 2=Orange, 3=Red

TIER_INT_TO_NAME = {0: "Green", 1: "Yellow", 2: "Orange", 3: "Red"}

# ---------------------------------------------------------------------------
# Tier thresholds (SRS.md Section 10.4, frozen)
# ---------------------------------------------------------------------------
TIER_THRESHOLDS = {
    "Green":  (0,  30),
    "Yellow": (30, 55),
    "Orange": (55, 75),
    "Red":    (75, 101),
}

# risk_score midpoints per tier (SRS.md Section 10.2, frozen)
TIER_MIDPOINTS = [15.0, 42.0, 64.0, 88.0]   # [Green, Yellow, Orange, Red]

# ---------------------------------------------------------------------------
# XGBoost training parameters
# ---------------------------------------------------------------------------
XGB_PARAMS = {
    "objective":        "multi:softprob",
    "num_class":        4,
    "eval_metric":      "mlogloss",
    "n_estimators":     400,
    "max_depth":        5,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "reg_alpha":        0.1,     # L1 regularisation -- helps with sparse IoT flag
    "reg_lambda":       1.0,     # L2 regularisation
    "random_state":     42,
    "n_jobs":           -1,
    "tree_method":      "hist",  # fast, works without GPU
    # enable_categorical=True lets XGBoost handle land_use_class as nominal
    "enable_categorical": False,  # set True once land_use_class is cast to pd.Categorical
}


# ===========================================================================
# Risk score and tier derivation (SRS.md Section 10.2 + 10.4 -- FROZEN)
# ===========================================================================

def compute_risk_score(proba: np.ndarray) -> np.ndarray:
    """
    Compute risk_score from XGBoost's 4-class softprob output.

    risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88
    (SRS.md Section 10.2, frozen formula -- do not alter)

    Args:
        proba: array of shape (n_samples, 4) from model.predict_proba()
               columns: [P(Green), P(Yellow), P(Orange), P(Red)]

    Returns: array of shape (n_samples,), values in [0, 100]
    """
    midpoints = np.array(TIER_MIDPOINTS)   # [15, 42, 64, 88]
    return (proba * midpoints).sum(axis=1)


def score_to_tier(risk_score: float) -> str:
    """
    Derive tier from risk_score using SRS.md Section 10.4 thresholds (frozen).

    Tier is ALWAYS derived from risk_score -- never predicted via argmax separately.
    This guarantees score and tier are mutually consistent by construction.
    """
    if risk_score < 30:
        return "Green"
    if risk_score < 55:
        return "Yellow"
    if risk_score < 75:
        return "Orange"
    return "Red"


def compute_confidence_score(
    model_class_probability: float,
    fs_band_width_penalty: float,
) -> float:
    """
    confidence_score = 100 * model_class_probability * (1 - fs_band_width_penalty)
    (SRS.md Section 10.3)

    model_class_probability: XGBoost's predicted probability for the winning tier.
    fs_band_width_penalty: from dynamic_features.compute_fs_band_width_penalty(),
                           0.0 if FS band does not straddle 1.0, up to 0.3.

    This is a confidence INDEX, not a calibrated probability. Never present as
    '88% probability of landslide' (SRS.md Section 10.3).
    """
    return float(min(100.0, max(0.0, 100.0 * model_class_probability * (1.0 - fs_band_width_penalty))))


# ===========================================================================
# Feature contributions (explainability panel, Phase 12 frontend)
# ===========================================================================

def extract_feature_contributions(model: xgb.XGBClassifier) -> dict:
    """
    Extract feature importances for the dashboard's explainability panel.

    Uses XGBoost's built-in gain-based importance (no extra dependency).
    Returns a dict: {feature_name: importance_score} sorted descending by importance.

    Phase 12 frontend reads these from risk_scores.feature_contributions JSONB
    (SRS.md Section 14 schema). Per-prediction SHAP values are left as a Phase 13
    enhancement if time permits -- gain importance covers the demo requirement.
    """
    importance = model.get_booster().get_score(importance_type="gain")
    # Map back to full feature names (XGBoost uses f0, f1, ... if feature names not set)
    booster = model.get_booster()
    feature_names = booster.feature_names
    if feature_names:
        named = {name: float(importance.get(name, 0.0)) for name in feature_names}
    else:
        named = {f"f{i}": float(importance.get(f"f{i}", 0.0))
                 for i in range(len(FEATURE_COLUMNS))}
    return dict(sorted(named.items(), key=lambda x: x[1], reverse=True))


# ===========================================================================
# Training pipeline
# ===========================================================================

def prepare_training_data(df: pd.DataFrame) -> tuple:
    """
    Prepare X (feature matrix) and y (target) for XGBoost training.

    Validates that all 25 feature columns are present, converts types,
    and returns (X, y, groups) where groups = event_id for LOEO-safe splitting.

    Args:
        df: enriched parquet DataFrame from dynamic_features.fill_dynamic_features_into_samples()

    Returns:
        X:      pd.DataFrame, shape (n_samples, 25)
        y:      pd.Series of tier_int (0-3)
        groups: pd.Series of event_id (None for negatives) for GroupShuffleSplit
    """
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        print(
            f"ERROR: Missing feature columns: {missing}\n"
            "  Run dynamic_features.py (Phase 6 Part 1) first.",
            file=sys.stderr,
        )
        sys.exit(1)

    if TARGET_COLUMN not in df.columns:
        print(
            f"ERROR: Target column '{TARGET_COLUMN}' not found in parquet.\n"
            "  Expected values 0-3 (Green/Yellow/Orange/Red tier_int).",
            file=sys.stderr,
        )
        sys.exit(1)

    X = df[FEATURE_COLUMNS].copy()

    # iot_anomaly_flag is bool -- convert to int for XGBoost
    X["iot_anomaly_flag"] = X["iot_anomaly_flag"].astype(int)

    # All None/NaN values stay as NaN -- XGBoost handles them natively with
    # tree_method='hist'. Never impute silently (per CLAUDE.md: fail loudly).
    nan_rates = X.isna().mean()
    high_nan = nan_rates[nan_rates > 0.5]
    if len(high_nan) > 0:
        warnings.warn(
            f"\n[train_fusion_model] HIGH NaN RATE in features:\n"
            + "\n".join(f"  {feat}: {rate*100:.0f}% null" for feat, rate in high_nan.items())
            + "\n  Check that Phase 1 (ingest) and Phase 5 (FS model) have run.",
            stacklevel=2,
        )

    y = df[TARGET_COLUMN].astype(int)

    # Groups for GroupShuffleSplit: use event_id to avoid data leakage
    # (all snapshots from one event must stay together in train or val)
    groups = df.get("event_id", pd.Series(["unknown"] * len(df)))

    return X, y, groups


def train_model(
    df: pd.DataFrame,
    val_split: float = 0.15,
    verbose: bool = True,
) -> tuple:
    """
    Train the XGBoost fusion model and return (model, val_metrics).

    Uses GroupShuffleSplit with event_id as the group key so that all snapshots
    of a held-out validation event stay together -- preventing leakage between
    train and val (consistent with the LOEO discipline in SRS.md Section 11).

    The full model (trained on all data) is saved for Phase 7/9 to use.
    The val split here is a quick sanity check only -- ground-truth LOEO
    validation is Phase 7's job.

    Args:
        df:        enriched DataFrame from dynamic_features.fill_dynamic_features_into_samples()
        val_split: fraction of events to hold out for quick validation (not LOEO)
        verbose:   print training progress

    Returns:
        model:       trained xgb.XGBClassifier (fitted on full dataset after validation)
        val_metrics: dict of val-set metrics
    """
    X, y, groups = prepare_training_data(df)

    n_samples   = len(X)
    n_events    = df["event_id"].nunique() if "event_id" in df.columns else "unknown"
    n_pos       = (df["sample_type"] == "positive").sum() if "sample_type" in df.columns else "unknown"
    n_neg       = (df["sample_type"] == "negative").sum() if "sample_type" in df.columns else "unknown"

    if verbose:
        print(f"\n[train_fusion_model] Training set summary:")
        print(f"  Total rows:    {n_samples}")
        print(f"  Unique events: {n_events}  (LOEO validation sample size -- NOT {n_samples})")
        print(f"  Positive rows: {n_pos}")
        print(f"  Negative rows: {n_neg}")
        print(f"  Features:      {len(FEATURE_COLUMNS)}")
        print()
        tier_dist = y.map(TIER_INT_TO_NAME).value_counts()
        print("  Tier distribution:")
        for tier, count in tier_dist.items():
            print(f"    {tier:8s}  {count:5d} rows  ({count/n_samples*100:.1f}%)")

    # -------------------------------------------------------------------------
    # Quick val split (sanity check only -- not LOEO, not the real validation)
    # -------------------------------------------------------------------------
    gss = GroupShuffleSplit(n_splits=1, test_size=val_split, random_state=42)
    train_idx, val_idx = next(gss.split(X, y, groups=groups))

    X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
    y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

    if verbose:
        print(f"\n[train_fusion_model] Split: {len(X_train)} train / {len(X_val)} val rows")

    # -------------------------------------------------------------------------
    # Train on split (for val metrics)
    # -------------------------------------------------------------------------
    model_split = xgb.XGBClassifier(**XGB_PARAMS)
    model_split.set_params(feature_names=FEATURE_COLUMNS)
    model_split.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=50 if verbose else False,
    )

    # Val metrics (sanity check -- Phase 7 runs real LOEO)
    proba_val  = model_split.predict_proba(X_val)
    scores_val = compute_risk_score(proba_val)
    tiers_val  = [score_to_tier(s) for s in scores_val]
    tiers_true = [TIER_INT_TO_NAME[i] for i in y_val]

    val_metrics = _compute_val_metrics(y_val.values, proba_val, tiers_true, tiers_val)
    if verbose:
        _print_val_metrics(val_metrics)

    # -------------------------------------------------------------------------
    # Retrain on full dataset (this is the model Phase 7/9 will use)
    # -------------------------------------------------------------------------
    if verbose:
        print("\n[train_fusion_model] Retraining on full dataset for Phase 7/9 ...")

    model_full = xgb.XGBClassifier(**XGB_PARAMS)
    model_full.set_params(feature_names=FEATURE_COLUMNS)
    model_full.fit(X, y, verbose=False)

    return model_full, val_metrics


def _compute_val_metrics(
    y_true: np.ndarray,
    proba: np.ndarray,
    tiers_true: list,
    tiers_pred: list,
) -> dict:
    """Compute validation metrics for the sanity-check split."""
    scores = compute_risk_score(proba)
    # Class probability for the predicted tier (used in confidence_score)
    pred_class_idx = proba.argmax(axis=1)
    pred_class_prob = proba[np.arange(len(proba)), pred_class_idx]
    mean_confidence = float(pred_class_prob.mean())

    # Tier-level accuracy (derived tier vs true tier)
    tier_match = [a == b for a, b in zip(tiers_true, tiers_pred)]
    tier_accuracy = float(sum(tier_match) / len(tier_match))

    # Orange/Red detection rate (the safety-critical classes)
    orange_red_true = [t in ("Orange", "Red") for t in tiers_true]
    orange_red_pred = [t in ("Orange", "Red") for t in tiers_pred]
    if any(orange_red_true):
        tp = sum(a and b for a, b in zip(orange_red_true, orange_red_pred))
        fn = sum(a and not b for a, b in zip(orange_red_true, orange_red_pred))
        orange_red_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    else:
        orange_red_recall = float("nan")

    return {
        "n_val_rows":         int(len(y_true)),
        "tier_accuracy":      round(tier_accuracy, 4),
        "orange_red_recall":  round(orange_red_recall, 4) if not math.isnan(orange_red_recall) else None,
        "mean_confidence":    round(mean_confidence, 4),
        "mean_risk_score":    round(float(scores.mean()), 2),
        "note": (
            "This is a quick sanity-check split -- NOT the LOEO validation. "
            "Ground-truth event-level performance is Phase 7's output (loeo_results table)."
        ),
    }


def _print_val_metrics(metrics: dict) -> None:
    print("\n[train_fusion_model] Validation metrics (sanity check only -- NOT LOEO):")
    print(f"  Val rows:           {metrics['n_val_rows']}")
    print(f"  Tier accuracy:      {metrics['tier_accuracy']*100:.1f}%")
    print(f"  Orange/Red recall:  {metrics['orange_red_recall']*100 if metrics['orange_red_recall'] is not None else 'N/A':.1f}%")
    print(f"  Mean confidence:    {metrics['mean_confidence']*100:.1f}%")
    print(f"  Mean risk score:    {metrics['mean_risk_score']:.1f}")
    print(f"\n  NOTE: {metrics['note']}")


# ===========================================================================
# Save / Load
# ===========================================================================

def save_model(model: xgb.XGBClassifier, val_metrics: dict) -> None:
    """
    Save trained model and metadata.

    Model: ml/models/fusion_model.json  (XGBoost native format)
    Meta:  ml/models/fusion_model_metadata.json
           Contains feature list, thresholds, training stats.
           Phase 7 (LOEO) and Phase 9 (lead-time) use this to reload consistently.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    model.save_model(str(MODEL_PATH))
    print(f"[train_fusion_model] Model saved -> {MODEL_PATH}")

    metadata = {
        "phase": 6,
        "srs_sections": ["10.2", "10.3", "10.4"],
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "tier_int_to_name": TIER_INT_TO_NAME,
        "tier_thresholds": TIER_THRESHOLDS,
        "risk_score_formula": "P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88",
        "tier_midpoints": TIER_MIDPOINTS,
        "confidence_score_formula": "100 * model_class_probability * (1 - fs_band_width_penalty)",
        "xgb_params": XGB_PARAMS,
        "val_metrics": val_metrics,
        "model_path": str(MODEL_PATH),
        "notes": [
            "antecedent_precipitation_index -- NEVER api_score (CLAUDE.md / SRS.md Section 9)",
            "tier is derived from risk_score, never from argmax separately (SRS.md Section 10.4)",
            "XGBoost only -- PSO-BP is never implemented (CLAUDE.md)",
            "soil_saturation_ratio = GWETROOT directly (SRS.md Section 10.1 frozen formula)",
        ],
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2))
    print(f"[train_fusion_model] Metadata saved -> {METADATA_PATH}")


def load_model() -> tuple:
    """
    Load trained model and metadata for Phase 7 (LOEO) and Phase 9 (lead-time).

    Returns: (model, metadata_dict)
    Fails loudly if model not found -- never returns a stub.
    """
    if not MODEL_PATH.exists():
        print(
            f"ERROR: {MODEL_PATH} not found.\n"
            "  Run train_fusion_model.py (Phase 6) to train the model first.",
            file=sys.stderr,
        )
        sys.exit(1)

    model = xgb.XGBClassifier()
    model.load_model(str(MODEL_PATH))

    metadata = json.loads(METADATA_PATH.read_text()) if METADATA_PATH.exists() else {}
    return model, metadata


# ===========================================================================
# CLI entry point
# ===========================================================================

import math   # needed for math.isnan in _compute_val_metrics

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6 Part 2: train XGBoost fusion model per SRS.md Section 10.2."
    )
    parser.add_argument(
        "--input", type=Path, default=SAMPLES_PARQUET,
        help=f"Enriched training parquet (default: {SAMPLES_PARQUET})",
    )
    parser.add_argument(
        "--val-split", type=float, default=0.15,
        help="Fraction of events to hold out for quick sanity-check validation (default: 0.15)",
    )
    parser.add_argument(
        "--skip-enrich", action="store_true",
        help="Skip dynamic feature enrichment (assume parquet is already enriched)",
    )
    args = parser.parse_args()

    print("=" * 65)
    print("HydraSense -- Phase 6 Part 2: Fusion Model Training")
    print("SRS.md Sections 10.2, 10.3, 10.4")
    print("XGBoost only. No PSO-BP. (CLAUDE.md)")
    print("=" * 65)

    # -------------------------------------------------------------------------
    # Step 1: Enrich parquet with dynamic features (Part 1) if not already done
    # -------------------------------------------------------------------------
    if not args.skip_enrich:
        print("\n[Step 1] Running dynamic feature enrichment (Phase 6 Part 1) ...")
        from ml.features.dynamic_features import fill_dynamic_features_into_samples
        df = fill_dynamic_features_into_samples(samples_path=args.input)
    else:
        print(f"\n[Step 1] Loading pre-enriched parquet from {args.input} ...")
        if not args.input.exists():
            print(f"ERROR: {args.input} not found.", file=sys.stderr)
            sys.exit(1)
        df = pd.read_parquet(args.input)
        print(f"  Loaded {len(df)} rows.")

    # -------------------------------------------------------------------------
    # Step 2: Train
    # -------------------------------------------------------------------------
    print("\n[Step 2] Training XGBoost fusion model ...")
    model, val_metrics = train_model(df, val_split=args.val_split, verbose=True)

    # -------------------------------------------------------------------------
    # Step 3: Feature contributions (for Phase 12 dashboard)
    # -------------------------------------------------------------------------
    print("\n[Step 3] Extracting feature contributions ...")
    contributions = extract_feature_contributions(model)
    print("  Top-10 features by gain importance:")
    for i, (feat, score) in enumerate(list(contributions.items())[:10], 1):
        print(f"    {i:2d}. {feat:42s}  {score:.1f}")

    # -------------------------------------------------------------------------
    # Step 4: Save
    # -------------------------------------------------------------------------
    print("\n[Step 4] Saving model and metadata ...")
    save_model(model, val_metrics)

    print("\n" + "=" * 65)
    print("PHASE 6 COMPLETE")
    print("=" * 65)
    print(f"  Model:    {MODEL_PATH}")
    print(f"  Metadata: {METADATA_PATH}")
    print()
    print("  Next steps:")
    print("    Phase 7 (loeo.py)     -- LOEO validation using this model")
    print("    Phase 8 (backend)     -- wires compute_dynamic_features() into /risk endpoints")
    print("    Phase 9 (lead-time)   -- reruns this model against forecast rainfall series")
    print()
    print("  IMPORTANT: report val tier_accuracy above as a sanity check only.")
    print(f"  The LOEO event count (~{df['event_id'].nunique() if 'event_id' in df.columns else '?'} events) is the real validation sample size.")
    print("  (SRS.md Section 11.2 -- timestep count != event count)")
    print("=" * 65)
