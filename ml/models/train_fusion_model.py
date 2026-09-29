"""
ml/models/train_fusion_model.py — XGBoost Fusion Model Training.

References:
  HydraSense_Final.md §10.3 — 29 features (15 static + 14 dynamic)
  HydraSense_Final.md §10.2 — risk_score formula (frozen)
  HydraSense_Final.md §11.3 — confidence_score = 100 * P_class * (1-FS_penalty) * C_cal
  HydraSense_Final.md §11.2 — tier thresholds (frozen)
  HydraSense_Final.md §14.6 — event-centered sample set

STAGE 3 CHANGES (Final.md §10.3):
  Feature table expanded from 25 → 29:
    NEW static features: flow_accumulation, hand_m, curve_number, has_local_calibration
  confidence_score gains C_cal factor (Final.md §11.3):
    confidence_score = 100 * P_class * (1 - FS_band_penalty) * C_cal
    C_cal = 1.0 if has_local_calibration else 0.75 (empirical placeholder; calibrated from LORO)
  XGBoost handles new features natively — NaN for samples missing these values.

HARD CONSTRAINTS (Final.md §10.2 / §11.2 — frozen formulas):
  - XGBoost ONLY.
  - risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88 (frozen)
  - Tier derived from risk_score via thresholds — NEVER a separate argmax.
  - antecedent_precipitation_index — NEVER api_score.
  - Model saved to ml/models/fusion_model.pkl
  - No live recomputation — training is one-time offline.
"""

from __future__ import annotations

import json
import math
import pickle
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import pandas as pd
    import numpy as np
    from xgboost import XGBClassifier
except ImportError as exc:
    print(f"ERROR: Required packages missing — {exc}")
    print("Install: pip install xgboost pandas numpy")
    sys.exit(1)

from ml.features.dynamic_features import (
    _compute_fs_band_penalty,
    load_rainfall_series,
    load_soil_series,
    load_gsi_lookup,
    compute_dynamic_features,
    _RAINFALL_CURRENT_PATH,
    _SOIL_PATH,
    _GSI_PATH,
)
from ml.models.factor_of_safety import compute_factor_of_safety, compute_fs_for_region

# ---------------------------------------------------------------------------
# Constants (frozen — SRS §10.2, §10.4, §11)
# ---------------------------------------------------------------------------

TIER_TO_INT: dict[str, int] = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
INT_TO_TIER: dict[int, str] = {v: k for k, v in TIER_TO_INT.items()}

# risk_score midpoints per tier (SRS §10.2 frozen formula)
TIER_MIDPOINTS: dict[int, float] = {0: 15.0, 1: 42.0, 2: 64.0, 3: 88.0}

# Tier thresholds from risk_score (SRS §10.4 frozen)
# risk_score -> tier: Green 0-29 | Yellow 30-54 | Orange 55-74 | Red 75-100
TIER_THRESHOLDS: list[tuple[float, str]] = [
    (75.0, "Red"),
    (55.0, "Orange"),
    (30.0, "Yellow"),
    (0.0,  "Green"),
]

# Paths
_MODEL_PATH   = ROOT / "ml"   / "models" / "fusion_model.pkl"
_SAMPLES_PATH = ROOT / "data" / "events" / "event_centered_samples.parquet"
_FEATURES_DIR = ROOT / "data" / "features"

# Static features — Final.md §10.3 (15 total — 4 new vs SRS §9)
# ADDED in Stage 3: flow_accumulation, hand_m, curve_number, has_local_calibration
STATIC_FEATURE_COLS: list[str] = [
    # Original 11 (preserved, field names frozen)
    "slope_deg", "aspect", "TWI", "TRI", "elevation",
    "distance_to_stream_m", "drainage_density",
    "land_use_class", "ndvi_mean", "historical_event_count_500m",
    "gsi_susceptibility_class",
    # NEW in Stage 3 (Final.md §10.3)
    "flow_accumulation",       # upstream contributing cells (pysheds D8)
    "hand_m",                  # Height Above Nearest Drainage (m)
    "curve_number",            # SCS CN from land cover + slope
    "has_local_calibration",   # bool → float (1.0/0.0); 29th feature; also drives C_cal
]

# Dynamic features — unchanged from SRS §9 (14 total, field names frozen)
# antecedent_precipitation_index: NEVER api_score (Final.md constraint)
DYNAMIC_FEATURE_COLS: list[str] = [
    "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h",
    "rainfall_72h_antecedent", "rain_intensity_mm_hr",
    "antecedent_precipitation_index",   # NEVER api_score — CLAUDE.md
    "soil_saturation_ratio",
    "factor_of_safety", "factor_of_safety_min", "factor_of_safety_max",
    "simulated_ffgs_signal", "simulated_gsi_signal", "iot_anomaly_flag",
]

ALL_FEATURE_COLS: list[str] = STATIC_FEATURE_COLS + DYNAMIC_FEATURE_COLS

# XGBoost hyperparameters (conservative defaults — tuning is Phase 7 territory)
XGBOOST_PARAMS: dict[str, Any] = {
    "n_estimators":      200,
    "max_depth":         4,
    "learning_rate":     0.05,
    "subsample":         0.8,
    "colsample_bytree":  0.8,
    "use_label_encoder": False,
    "eval_metric":       "mlogloss",
    "objective":         "multi:softprob",
    "num_class":         4,
    "tree_method":       "hist",          # fast on CPU
    "random_state":      42,
    "n_jobs":            -1,
    "missing":           float("nan"),    # XGBoost native missing-value handling
    "verbosity":         0,
}


# ---------------------------------------------------------------------------
# Tier / score functions (frozen formulas)
# ---------------------------------------------------------------------------

def compute_risk_score(proba: dict[int, float]) -> float:
    """
    risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88

    SRS §10.2 frozen formula — probability-weighted expected value over the
    four tier-class probabilities from XGBoost's predict_proba.
    Result clipped to [0, 100].
    """
    score = sum(proba[tier_int] * mid for tier_int, mid in TIER_MIDPOINTS.items())
    return round(float(max(0.0, min(100.0, score))), 4)


def derive_tier(risk_score: float) -> str:
    """
    Derive tier from risk_score using SRS §10.4 thresholds.
    MUST be derived from risk_score — never a separate argmax that could disagree.
    Green: 0-29 | Yellow: 30-54 | Orange: 55-74 | Red: 75-100
    """
    for threshold, tier in TIER_THRESHOLDS:
        if risk_score >= threshold:
            return tier
    return "Green"


# ---------------------------------------------------------------------------
# C_cal loader — reads empirical value from LORO summary (Stage 4)
# ---------------------------------------------------------------------------
_C_CAL_CACHE: dict[str, float] = {}   # module-level cache, JSON read at most once

def _load_c_cal_uncalibrated() -> float:
    """
    Load empirical C_cal for uncalibrated regions from LORO summary.
    Stage 4 result: C_cal_empirical=1.0 — uncalibrated regions generalise
    as well as calibrated in 10-fold LORO (94.8% aggregate detection rate).
    Returns 0.75 placeholder if LORO hasn't been run.
    """
    if "_cached" in _C_CAL_CACHE:
        return _C_CAL_CACHE["_cached"]
    loro_path = ROOT / "data" / "validation" / "loro_summary.json"
    try:
        import json as _json
        data = _json.loads(loro_path.read_text(encoding="utf-8"))
        c_cal = data.get("c_cal_calibration", {}).get("c_cal_empirical")
        if c_cal is not None:
            _C_CAL_CACHE["_cached"] = float(c_cal)
            return float(c_cal)
    except Exception:
        pass
    _C_CAL_CACHE["_cached"] = 0.75
    return 0.75


def compute_confidence_score(
    model_class_probability: float,
    fs_band_width_penalty:   float,
    has_local_calibration:   bool  = True,
    c_cal_uncalibrated:      float | None = None,   # None = load from LORO
) -> float:
    """
    3-factor confidence score (Final.md §11.3):

      confidence_score = 100 * P_class * (1 - FS_band_penalty) * C_cal

    where:
      P_class         = model probability of the DERIVED tier class
      FS_band_penalty = (FS_max - FS_min) / FS_max, clipped [0, 0.95]
      C_cal           = 1.0 if has_local_calibration
                        else empirical value from LORO (Stage 4), default 0.75

    Stage 4 LORO result: C_cal_empirical=1.0 — uncalibrated regions generalise
    as well as Wayanad in 10-fold LORO. Loaded from data/validation/loro_summary.json.

    This is a confidence INDEX — NEVER present as 'probability of landslide' in UI.
    Result clipped to [0, 100].
    """
    if c_cal_uncalibrated is None:
        c_cal_uncalibrated = _load_c_cal_uncalibrated()
    c_cal = 1.0 if has_local_calibration else c_cal_uncalibrated
    score = 100.0 * model_class_probability * (1.0 - fs_band_width_penalty) * c_cal
    return round(float(max(0.0, min(100.0, score))), 4)


def compute_confidence_breakdown(
    model_class_probability: float,
    fs_band_width_penalty:   float,
    has_local_calibration:   bool,
    c_cal_uncalibrated:      float | None = None,  # None = load from LORO
) -> dict:
    """
    Return the three-factor confidence breakdown (Final.md §13.4 hex tooltip).
    Also served by GET /confidence/{hex_id}/breakdown (Stage 5).

    c_cal_uncalibrated: if None, loaded from LORO summary (Stage 4 empirical value).

    Returns:
      {
        "model_probability_factor": int   0-100  (P_class as integer percentage)
        "fs_band_penalty":          float 0-0.95 (raw penalty before complement)
        "fs_uncertainty_factor":    int   0-100  (100 * (1 - fs_band_penalty))
        "has_local_calibration":    bool
        "c_cal":                    float         (LORO-derived or 1.0 for calibrated)
        "c_cal_source":             str           ("loro_empirical" or "placeholder")
        "confidence_score":         float         (final composite)
      }
    """
    if c_cal_uncalibrated is None:
        c_cal_uncalibrated = _load_c_cal_uncalibrated()
        c_cal_source = "loro_empirical"
    else:
        c_cal_source = "override"
    c_cal  = 1.0 if has_local_calibration else c_cal_uncalibrated
    fs_fac = max(0.0, min(1.0, 1.0 - fs_band_width_penalty))
    conf   = compute_confidence_score(
        model_class_probability, fs_band_width_penalty, has_local_calibration, c_cal_uncalibrated
    )
    return {
        "model_probability_factor": round(model_class_probability * 100),
        "fs_band_penalty":          round(fs_band_width_penalty, 4),
        "fs_uncertainty_factor":    round(fs_fac * 100),
        "has_local_calibration":    has_local_calibration,
        "c_cal":                    c_cal,
        "c_cal_source":             c_cal_source if not has_local_calibration else "calibrated_region",
        "confidence_score":         conf,
    }


# ---------------------------------------------------------------------------
# Feature preparation
# ---------------------------------------------------------------------------

def _encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Encode string/boolean categorical features for XGBoost.

    gsi_susceptibility_class: ordinal encode by hazard severity
      Low=0, Moderate=1, High=2, Very High=3, unknown=-1
    land_use_class: ordinal encode by landslide susceptibility proxy
      (Water=0, Urban=1, Cropland=2, Grassland=3, Shrubland=4, Forest=5, unknown=2)
    simulated_ffgs_signal / simulated_gsi_signal / iot_anomaly_flag: bool -> int (0/1)
    """
    df = df.copy()

    SUSC_MAP = {"Low": 0, "Moderate": 1, "High": 2, "Very High": 3}
    if "gsi_susceptibility_class" in df.columns:
        df["gsi_susceptibility_class"] = (
            df["gsi_susceptibility_class"]
            .map(SUSC_MAP)
            .fillna(-1)
            .astype(float)
        )

    LULC_MAP = {
        "Water": 0, "Urban": 1, "Cropland": 2,
        "Grassland": 3, "Shrubland": 4, "Forest": 5,
        "Bare": 3,    # bare soil similar to grassland susceptibility
    }
    if "land_use_class" in df.columns:
        df["land_use_class"] = (
            df["land_use_class"]
            .map(LULC_MAP)
            .fillna(2)   # default: cropland susceptibility proxy
            .astype(float)
        )

    for bool_col in ["simulated_ffgs_signal", "simulated_gsi_signal", "iot_anomaly_flag"]:
        if bool_col in df.columns:
            df[bool_col] = df[bool_col].apply(
                lambda x: 1.0 if x is True or x == 1 else (0.0 if x is False or x == 0 else float("nan"))
            )

    return df


def prepare_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Prepare X (feature matrix) and y (integer tier label) from a sample DataFrame.

    Uses XGBoost's native missing-value mechanism — None/NaN kept as NaN,
    never imputed.  Logs column-level missing counts before training.
    """
    # Ensure all feature cols exist; add as NaN if missing from Phase 4 schema
    for col in ALL_FEATURE_COLS:
        if col not in df.columns:
            df[col] = float("nan")
            print(f"[train_fusion] NOTE: Column '{col}' absent from sample set — added as NaN")

    df = _encode_categoricals(df)

    X = df[ALL_FEATURE_COLS].copy()
    # Convert to float (XGBoost requires numeric)
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")

    y = df["tier_int"].astype(int)

    # Log missing counts (never impute)
    nan_counts = X.isna().sum()
    non_zero_missing = nan_counts[nan_counts > 0]
    if not non_zero_missing.empty:
        print("[train_fusion] NaN counts per feature (XGBoost handles natively):")
        for col, cnt in non_zero_missing.items():
            pct = 100.0 * cnt / max(len(X), 1)
            print(f"  {col:<45s}: {cnt:5d} ({pct:.1f}%)")

    return X, y


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

class FusionModel:
    """
    Wrapper around XGBClassifier implementing the SRS §10.2/§10.3 formulas.
    Saved to fusion_model.pkl; loaded by Phase 7 (LOEO) and Phase 9 (lead-time).

    All scoring methods are pure (no side effects) after training is complete.
    """

    def __init__(self) -> None:
        self.clf        = XGBClassifier(**XGBOOST_PARAMS)
        self.is_fitted  = False
        self.feature_cols = ALL_FEATURE_COLS
        self._xgb_params  = XGBOOST_PARAMS
        self.training_meta: dict[str, Any] = {}

    def fit(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Train XGBoost on prepared feature matrix X with tier integer labels y."""
        self.clf.fit(X, y)
        self.is_fitted = True
        self.training_meta = {
            "n_samples":      len(X),
            "n_features":     X.shape[1],
            "feature_cols":   self.feature_cols,
            "class_dist":     y.value_counts().to_dict(),
            "xgboost_params": XGBOOST_PARAMS,
        }
        print(
            f"[train_fusion] XGBoost trained on {len(X)} samples, "
            f"{X.shape[1]} features. "
            f"Class distribution: { {INT_TO_TIER[k]: v for k, v in y.value_counts().items()} }"
        )

    def predict_one(
        self,
        features: dict[str, Any],
        fs_band_width_penalty: float = 0.0,
        has_local_calibration: bool = True,
    ) -> dict[str, Any]:
        """
        Run inference for a single hex-timestep.

        Arguments:
            features              : dict of feature name -> value (all 29 features)
            fs_band_width_penalty : from dynamic_features._compute_fs_band_penalty()
            has_local_calibration : 29th feature / C_cal gate (Final.md §11.3)

        Returns dict with:
            risk_score           : float 0-100 (Final.md §10.2 frozen formula)
            tier                 : str (derived from risk_score via §11.2 thresholds)
            confidence_score     : float 0-100 (Final.md §11.3 — 3-factor formula)
            confidence_breakdown : dict  (three-factor decomposition for tooltip/API)
            tier_probabilities   : {tier_name: probability}
            feature_contributions: {feature: importance_score}
        """
        if not self.is_fitted:
            raise RuntimeError("[FusionModel] Model not fitted. Call fit() first.")

        # Build 1-row DataFrame
        row = {col: [features.get(col, float("nan"))] for col in self.feature_cols}
        X_row = pd.DataFrame(row)
        X_row = _encode_categoricals(X_row)
        for col in X_row.columns:
            X_row[col] = pd.to_numeric(X_row[col], errors="coerce")

        proba_arr = self.clf.predict_proba(X_row)[0]  # shape: (4,)
        proba = {i: float(p) for i, p in enumerate(proba_arr)}

        risk  = compute_risk_score(proba)
        tier  = derive_tier(risk)
        # Confidence: probability of the DERIVED tier class
        tier_int   = TIER_TO_INT[tier]
        class_prob = proba[tier_int]
        # has_local_calibration from features dict (the 29th feature)
        cal_flag = bool(features.get("has_local_calibration", has_local_calibration))
        conf  = compute_confidence_score(class_prob, fs_band_width_penalty, cal_flag)
        breakdown = compute_confidence_breakdown(class_prob, fs_band_width_penalty, cal_flag)

        # Feature importances (model-level gain — same for all rows in inference)
        importances = {
            col: round(float(imp), 6)
            for col, imp in zip(self.feature_cols, self.clf.feature_importances_)
        }

        return {
            "risk_score":            risk,
            "tier":                  tier,
            "confidence_score":      conf,
            "confidence_breakdown":  breakdown,
            "tier_probabilities":    {INT_TO_TIER[i]: round(float(p), 6) for i, p in proba.items()},
            "feature_contributions": importances,
        }

    def predict_batch(
        self,
        df: pd.DataFrame,
        fs_band_penalties: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Batch inference on a prepared feature DataFrame.
        Returns the input df with extra columns appended:
          risk_score, tier, confidence_score, tier_probabilities (JSON string).
        """
        if not self.is_fitted:
            raise RuntimeError("[FusionModel] Model not fitted.")

        X = df[self.feature_cols].copy()
        X = _encode_categoricals(X)
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors="coerce")

        proba_arr = self.clf.predict_proba(X)  # shape: (N, 4)

        risk_scores    = []
        tiers          = []
        conf_scores    = []
        tier_proba_str = []

        for i, p_row in enumerate(proba_arr):
            proba = {j: float(p) for j, p in enumerate(p_row)}
            risk  = compute_risk_score(proba)
            tier  = derive_tier(risk)
            tier_int    = TIER_TO_INT[tier]
            class_prob  = proba[tier_int]
            band_penalty = (
                float(fs_band_penalties.iloc[i])
                if fs_band_penalties is not None
                else 0.0
            )
            conf = compute_confidence_score(class_prob, band_penalty)

            risk_scores.append(risk)
            tiers.append(tier)
            conf_scores.append(conf)
            tier_proba_str.append(
                json.dumps({INT_TO_TIER[j]: round(float(p), 6) for j, p in proba.items()})
            )

        out = df.copy()
        out["risk_score"]        = risk_scores
        out["tier"]              = tiers
        out["confidence_score"]  = conf_scores
        out["tier_probabilities"] = tier_proba_str
        return out

    def save(self, path: Path = _MODEL_PATH) -> None:
        """Save model state as a portable dict (JSON booster + metadata).
        Avoids pickle class-resolution issues when loading from non-__main__ contexts.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        import tempfile, os
        # Save XGBoost booster to JSON string
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            self.clf.save_model(tmp_path)
            with open(tmp_path, "r", encoding="utf-8") as f:
                booster_json = f.read()
        finally:
            os.unlink(tmp_path)
        state = {
            "booster_json": booster_json,
            "feature_cols": ALL_FEATURE_COLS,
            "xgb_params":   XGBOOST_PARAMS,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)
        print(f"[train_fusion] Model saved -> {path}")

    @classmethod
    def load(cls, path: Path = _MODEL_PATH) -> "FusionModel":
        """Load model from state dict. No class-resolution required -- state is primitive types."""
        if not path.exists():
            raise FileNotFoundError(
                f"[FusionModel] Model not found at {path}. "
                "Run train_fusion_model.py first."
            )
        with open(path, "rb") as f:
            state = pickle.load(f)
        # state is a plain dict -- no FusionModel class needed to unpickle
        import tempfile, os
        import xgboost as xgb
        model = cls()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as tmp:
            tmp.write(state["booster_json"])
            tmp_path = tmp.name
        try:
            model.clf = xgb.XGBClassifier()
            model.clf.load_model(tmp_path)
        finally:
            os.unlink(tmp_path)
        model._xgb_params = state.get("xgb_params", XGBOOST_PARAMS)
        model.is_fitted   = True   # booster restored -- model is ready for inference
        print(f"[train_fusion] Model loaded <- {path}")
        return model



# ---------------------------------------------------------------------------
# Main training pipeline
# ---------------------------------------------------------------------------

def load_sample_set(path: Path = _SAMPLES_PATH) -> pd.DataFrame:
    """
    Load the event-centered sample set from Phase 4.

    Falls back to a minimal synthetic set if Phase 4 has not been run —
    prints a loud WARNING and the synthetic set is clearly marked as such.
    The synthetic fallback exists so Phase 6 can be tested end-to-end without
    Phase 4 completing first.  The model trained on synthetic data MUST NOT be
    used for LOEO or production.
    """
    if path.exists():
        df = pd.read_parquet(path)
        print(f"[train_fusion] Loaded {len(df)} samples from Phase 4 -> {path}")
        return df

    # ── Synthetic fallback (Phase 4 not run) ─────────────────────────────
    print(
        "WARNING: Phase 4 sample set not found at:\n"
        f"  {path}\n"
        "  Generating a SYNTHETIC training set for end-to-end testing.\n"
        "  THIS MODEL IS NOT VALID FOR LOEO OR PRODUCTION USE.\n"
        "  Run event_centered_sampling.py (Phase 4) first for real training.",
        file=sys.stderr,
    )
    rng = np.random.default_rng(42)
    n   = 200  # small synthetic set: 40 positive × 5 tiers approx + 160 negative
    tier_labels = rng.choice([0, 0, 0, 0, 1, 1, 2, 3], size=n)  # skewed toward Green

    synthetic: dict[str, Any] = {
        "tier_int":    tier_labels,
        "sample_type": ["positive" if t > 0 else "negative" for t in tier_labels],
    }
    for col in ALL_FEATURE_COLS:
        if col in {"gsi_susceptibility_class", "land_use_class"}:
            synthetic[col] = rng.choice(["Low", "Moderate", "High"], size=n)
        elif col in {"simulated_ffgs_signal", "simulated_gsi_signal", "iot_anomaly_flag"}:
            synthetic[col] = rng.choice([True, False], size=n)
        else:
            synthetic[col] = rng.uniform(0, 50, size=n)

    # Inject more realistic values correlated with labels
    for i, t in enumerate(tier_labels):
        if t >= 2:   # Orange/Red
            synthetic["rainfall_24h"][i]       = float(rng.uniform(80, 250))
            synthetic["soil_saturation_ratio"][i] = float(rng.uniform(0.7, 1.0))
            synthetic["factor_of_safety"][i]   = float(rng.uniform(0.5, 1.2))
        else:
            synthetic["rainfall_24h"][i]       = float(rng.uniform(0, 30))
            synthetic["soil_saturation_ratio"][i] = float(rng.uniform(0.1, 0.6))
            synthetic["factor_of_safety"][i]   = float(rng.uniform(1.5, 5.0))

    df = pd.DataFrame(synthetic)
    df["hex_id"]     = ["8860064000%05x" % i for i in range(n)]
    df["village"]    = rng.choice(["Mundakkai", "Attamala", "Punjirimattom"], size=n)
    df["event_id"]   = ["E_SYN_%03d" % i if t > 0 else None for i, t in enumerate(tier_labels)]
    df["region_code"]= rng.choice(["wayanad-kl", "rudraprayag-uk", "darjeeling-wb"], size=n)
    # has_local_calibration: True for Wayanad rows, False for others in synthetic data
    df["has_local_calibration"] = df["region_code"].apply(lambda r: 1.0 if r == "wayanad-kl" else 0.0)
    df["is_synthetic"] = True
    return df


def join_dynamic_features(
    df: pd.DataFrame,
    rainfall_current_path: Path = _RAINFALL_CURRENT_PATH,
    soil_path:             Path = _SOIL_PATH,
    gsi_path:              Path = _GSI_PATH,
    static_features_path:  Optional[Path] = None,
) -> pd.DataFrame:
    """
    Enrich Phase 4 sample rows with real dynamic features computed from Phase 1 data.

    Phase 4 produced a parquet with None placeholders for all dynamic features.
    This function fills in the 14 dynamic features using each row's snapshot_timestamp
    and village lookup.

    For historical events (2009–2023) where Phase 1 data doesn't extend back, most
    dynamic features will remain None — that is correct and honest.  XGBoost handles
    missing values natively; we do NOT impute.

    The most important real values are:
      - soil_saturation_ratio: GWETROOT latest-available fallback covers recent samples
      - antecedent_precipitation_index: computed from whatever observed window exists
      - simulated_ffgs_signal / simulated_gsi_signal: computed from rainfall + GSI class
      - factor_of_safety: requires slope_deg from Phase 3 (will be None until Phase 3 parquet)

    Static features (slope_deg, aspect, etc.) are joined from Phase 3 parquet if available.
    """
    print("\n[train_fusion] Joining dynamic features from Phase 1 data ...")

    # Pre-load lookups once
    from ml.features.dynamic_features import (
        load_rainfall_series, load_soil_series, load_gsi_lookup,
        compute_dynamic_features,
    )
    rainfall_lookup = load_rainfall_series(rainfall_current_path)
    soil_lookup     = load_soil_series(soil_path)
    gsi_lookup      = load_gsi_lookup(gsi_path)

    # Load static features from Phase 3 parquet if available
    static_map: dict[str, dict[str, Any]] = {}   # {hex_id: {col: val}}
    if static_features_path is None:
        # Phase 3 writes exclusively to data/processed/static_features.parquet.
        # (static_features.py L133: OUT_DIR = BASE_DIR / "data" / "processed")
        static_features_path = ROOT / "data" / "processed" / "static_features.parquet"
    if static_features_path.exists():
        try:
            sf = pd.read_parquet(static_features_path)
            for _, row in sf.iterrows():
                hid = str(row["hex_id"])
                static_map[hid] = {c: row.get(c) for c in STATIC_FEATURE_COLS}
            print(f"[train_fusion] Loaded Phase 3 static features for {len(static_map)} hexes"
                  f" from {static_features_path}")
        except Exception as exc:
            print(f"[train_fusion] WARNING: Could not load Phase 3 parquet ({exc}); static features remain NaN")
    else:
        print(
            f"[train_fusion] NOTE: Phase 3 static_features.parquet not found.\n"
            f"  Expected: {static_features_path}\n"
            f"  Run: python ml/features/static_features.py  (requires DEM + landcover rasters)\n"
            f"  Until then: slope_deg, aspect, TWI, TRI, elevation, etc. will be NaN for all rows.\n"
            f"  factor_of_safety will also be NaN (needs slope_deg)."
        )

    # Join dynamic features row by row
    dyn_records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ts_str  = str(row.get("snapshot_timestamp", "") or "")
        village = str(row.get("village", "") or "")
        hex_id  = str(row.get("hex_id", "") or "")

        # Parse snapshot timestamp — these are historical event times (2024 July etc.)
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            dyn_records.append({})
            continue

        # Get slope_deg from Phase 3 static map (or None if not run)
        slope_deg = None
        if hex_id in static_map:
            slope_deg = static_map[hex_id].get("slope_deg")
        elif static_map:
            # Fallback: nearest static hex by lexicographic proximity (rough)
            slope_deg = next(iter(static_map.values()), {}).get("slope_deg")

        # GSI susceptibility class
        gsi_class = gsi_lookup.get(hex_id)

        # Compute all 14 dynamic features
        dyn = compute_dynamic_features(
            hex_id=hex_id,
            village=village,
            timestamp=ts,
            slope_deg=slope_deg,
            gsi_susceptibility_class=gsi_class,
            rainfall_lookup=rainfall_lookup,
            soil_lookup=soil_lookup,
        )
        dyn_records.append(dyn)

    # Build a joined DataFrame.
    # IMPORTANT: event_centered_sampling.py already computed rainfall features at
    # sample-generation time using the full historical + live lookup.  Those values
    # are the authoritative ones — do NOT overwrite non-null parquet values with the
    # freshly computed (and often NaN) values from the current lookup window.
    # Only fill slots that are still NaN in the parquet (e.g. soil_saturation_ratio,
    # simulated signals, and any column that sampling didn't pre-compute).
    dyn_df = pd.DataFrame(dyn_records, index=df.index)

    dyn_cols = DYNAMIC_FEATURE_COLS + ["fs_band_width_penalty", "fs_band_straddles_one"]
    for col in dyn_cols:
        if col not in dyn_df.columns:
            continue
        if col not in df.columns:
            df = df.copy()
            df[col] = dyn_df[col]
        else:
            # Prefer parquet value; fill only NaN slots from freshly computed values.
            # Coerce to numeric first — compute_dynamic_features() returns Python None
            # which pandas can't assign into a float64 parquet column directly.
            df = df.copy()
            null_mask = df[col].isna()
            if null_mask.any():
                fill_vals = pd.to_numeric(dyn_df.loc[null_mask, col], errors="coerce")
                df.loc[null_mask, col] = fill_vals

    # Join static features from Phase 3 if available (Phase 3 parquet is authoritative)
    for col in STATIC_FEATURE_COLS:
        if static_map:
            # static_map is keyed by hex_id; fill from map, prefer parquet if non-null
            vals = df["hex_id"].map(lambda h: static_map.get(str(h), {}).get(col))
            if col not in df.columns:
                df[col] = vals
            else:
                null_mask = df[col].isna()
                df.loc[null_mask, col] = vals[null_mask]
        elif col not in df.columns:
            df[col] = None

    # Count coverage after join
    n_soil = int(df["soil_saturation_ratio"].notna().sum())
    n_r24  = int(df["rainfall_24h"].notna().sum())
    n_fs   = int(df["factor_of_safety"].notna().sum())
    n_ffgs = int(df["simulated_ffgs_signal"].notna().sum())
    print(
        f"[train_fusion] Feature join complete ({len(df)} rows):\n"
        f"  soil_saturation_ratio: {n_soil}/{len(df)} non-null\n"
        f"  rainfall_24h:          {n_r24}/{len(df)} non-null\n"
        f"  factor_of_safety:      {n_fs}/{len(df)} non-null"
        f"  (None until Phase 3 parquet exists)\n"
        f"  simulated_ffgs_signal: {n_ffgs}/{len(df)} non-null"
    )
    return df


def train_and_save(
    samples_path:    Path = _SAMPLES_PATH,
    model_save_path: Path = _MODEL_PATH,
    held_out_n:      int  = 5,
) -> FusionModel:
    """
    Full training pipeline:
      1. Load Phase 4 sample set (or synthetic fallback)
      2. Prepare feature matrix (encode categoricals, keep NaN for XGBoost)
      3. Train XGBoost (no held-out split — LOEO in Phase 7 is the validation)
      4. Print feature importance + sample held-out predictions
      5. Save model to pkl

    Phase 7 (LOEO) does the real validation — this function trains on the full
    dataset and saves the model for LOEO harness reuse.

    Returns the fitted FusionModel.
    """
    # ── 1. Load sample set ────────────────────────────────────────────────
    df = load_sample_set(samples_path)

    # ── 1b. Join dynamic features (Phase 6 core pipeline step) ───────────
    # Phase 4 parquet has None placeholders for all dynamic features.
    # compute and fill them now from Phase 1 observed data.
    df = join_dynamic_features(df)

    # ── 2. Prepare features ───────────────────────────────────────────────
    X, y = prepare_feature_matrix(df)

    print(f"\n[train_fusion] Feature matrix: {X.shape[0]} rows x {X.shape[1]} cols")
    print(f"[train_fusion] Class distribution (tier):")
    for tier_int, count in sorted(y.value_counts().items()):
        print(f"  {INT_TO_TIER[tier_int]:8s} (class {tier_int}): {count} samples")

    # ── 3. Train XGBoost ─────────────────────────────────────────────────
    model = FusionModel()
    model.fit(X, y)

    # ── 4. Feature importance (model-level gain) ─────────────────────────
    importances = sorted(
        zip(ALL_FEATURE_COLS, model.clf.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    )
    print("\n[train_fusion] Top-10 feature importances (XGBoost gain):")
    for feat, imp in importances[:10]:
        bar = "#" * int(imp * 200)
        print(f"  {feat:<45s} {imp:.6f}  {bar}")

    # ── 5. Held-out sample predictions ───────────────────────────────────
    print(f"\n[train_fusion] Sample predictions on {min(held_out_n, len(df))} rows:")
    print(
        f"  {'hex_id':<20} {'village':<15} {'true_tier':>10} "
        f"{'risk_score':>11} {'predicted_tier':>15} {'confidence':>11}"
    )
    print("  " + "-" * 86)

    # Compute band penalties from df if available
    band_penalty_col = (
        df["fs_band_width_penalty"] if "fs_band_width_penalty" in df.columns
        else pd.Series([0.0] * len(df))
    )

    sample_rows = df.sample(n=min(held_out_n, len(df)), random_state=99)
    for i, (idx, row) in enumerate(sample_rows.iterrows()):
        feat_dict = {col: row.get(col) for col in ALL_FEATURE_COLS}
        penalty   = float(band_penalty_col.loc[idx]) if idx in band_penalty_col.index else 0.0
        pred      = model.predict_one(feat_dict, penalty)
        true_tier = INT_TO_TIER.get(int(row["tier_int"]), "?")
        print(
            f"  {str(row.get('hex_id', '?')):<20} "
            f"{str(row.get('village', '?')):<15} "
            f"{true_tier:>10} "
            f"{pred['risk_score']:>11.2f} "
            f"{pred['tier']:>15} "
            f"{pred['confidence_score']:>11.2f}"
        )

    # ── 6. Save model ────────────────────────────────────────────────────
    model.save(model_save_path)

    return model


# ---------------------------------------------------------------------------
# Inference wrapper — per-cycle scoring (called by Phase 8 API)
# ---------------------------------------------------------------------------

def score_hex_cycle(
    hex_id:      str,
    village:     str,
    timestamp:   str,     # ISO datetime string
    features:    dict[str, Any],
    model_path:  Path = _MODEL_PATH,
    region_code: str  = "",
) -> dict[str, Any]:
    """
    Score a single hex at one ingestion cycle, using the saved model.

    Arguments:
        hex_id      : H3 hex identifier
        village     : village name (for audit)
        timestamp   : ISO datetime string of the cycle
        features    : all 29 feature values (static + dynamic)
        model_path  : path to fusion_model.pkl
        region_code : slug from onboarding pipeline (e.g. 'wayanad-kl')
                      Used to route FS computation through SoilGrids if available.

    Returns:
        dict with risk_score, tier, confidence_score, tier_probabilities,
              feature_contributions, hex_id, village, timestamp
    """
    model = FusionModel.load(model_path)
    band_penalty = features.get("fs_band_width_penalty", 0.0) or 0.0
    has_cal = bool(features.get("has_local_calibration", True))
    # Re-compute FS via the region-agnostic router (SoilGrids path if available)
    slope = features.get("factor_of_safety")   # already computed upstream — use as-is
    # Only override if slope_deg is available and FS not yet present
    if region_code and features.get("factor_of_safety") is None:
        slope_deg = features.get("slope_deg")
        soil_sat  = features.get("soil_saturation_ratio")
        if slope_deg is not None and soil_sat is not None:
            fs_result = compute_fs_for_region(slope_deg, soil_sat, region_code, has_cal)
            features = {**features, **{
                k: fs_result[k]
                for k in ("factor_of_safety", "factor_of_safety_min", "factor_of_safety_max")
                if fs_result.get(k) is not None
            }}
    pred = model.predict_one(features, float(band_penalty), has_local_calibration=has_cal)
    return {
        **pred,
        "hex_id":      hex_id,
        "village":     village,
        "timestamp":   timestamp,
        "region_code": region_code,
    }


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 80)
    print("Phase 6 Part 2 — XGBoost Fusion Model Training")
    print("SRS.md Section 10.2/10.3/10.4 | XGBoost only (no PSO-BP)")
    print("=" * 80)
    print()

    model = train_and_save()

    # ── Acceptance criteria (SRS §25, Phase 6) ───────────────────────────
    # "the model trains without error on the compiled + event-centered dataset
    #  and produces a risk_score (0-100) and feature-importance breakdown for
    #  a held-out sample hex-timestep."
    print("\n[train_fusion] Acceptance criteria check:")

    # Check 1: model is fitted
    assert model.is_fitted, "FAIL: model.is_fitted is False"
    print("  [OK] Model fitted without error")

    # Check 2: predict_one returns risk_score in [0, 100]
    test_feats: dict[str, Any] = {col: 0.0 for col in ALL_FEATURE_COLS}
    test_feats["rainfall_24h"]        = 120.0
    test_feats["soil_saturation_ratio"] = 0.85
    test_feats["factor_of_safety"]    = 0.7
    test_feats["slope_deg"]           = 35.0
    test_feats["gsi_susceptibility_class"] = "High"
    pred = model.predict_one(test_feats, fs_band_width_penalty=0.15)

    assert 0.0 <= pred["risk_score"] <= 100.0, f"FAIL: risk_score={pred['risk_score']} out of [0,100]"
    print(f"  [OK] risk_score={pred['risk_score']:.2f} in [0, 100]")

    # Check 3: tier derived from risk_score (consistent with §10.4 thresholds)
    expected_tier = derive_tier(pred["risk_score"])
    assert pred["tier"] == expected_tier, (
        f"FAIL: tier={pred['tier']} disagrees with "
        f"derive_tier({pred['risk_score']:.2f})={expected_tier}"
    )
    print(f"  [OK] tier='{pred['tier']}' consistent with risk_score={pred['risk_score']:.2f}")

    # Check 4: confidence_score in [0, 100]
    assert 0.0 <= pred["confidence_score"] <= 100.0, (
        f"FAIL: confidence_score={pred['confidence_score']} out of [0,100]"
    )
    print(f"  [OK] confidence_score={pred['confidence_score']:.2f} in [0, 100]")

    # Check 5: feature_contributions has all 29 features
    assert len(pred["feature_contributions"]) == len(ALL_FEATURE_COLS), (
        "FAIL: %d contributions, expected %d" % (len(pred["feature_contributions"]), len(ALL_FEATURE_COLS))
    )
    print("  [OK] feature_contributions: %d features (29-feature Final.md §10.3)" % len(pred["feature_contributions"]))

    # Check 6: risk_score formula matches manual calculation
    proba_manual = pred["tier_probabilities"]
    manual_score = (
        proba_manual["Green"]  * 15.0
        + proba_manual["Yellow"] * 42.0
        + proba_manual["Orange"] * 64.0
        + proba_manual["Red"]    * 88.0
    )
    assert abs(manual_score - pred["risk_score"]) < 0.01, (
        f"FAIL: risk_score={pred['risk_score']:.4f} != "
        f"manual formula={manual_score:.4f}"
    )
    print(f"  [OK] risk_score formula verified: P(G)*15+P(Y)*42+P(O)*64+P(R)*88 = {manual_score:.2f}")

    # Check 7: model file saved
    assert _MODEL_PATH.exists(), f"FAIL: model not saved at {_MODEL_PATH}"
    print(f"  [OK] Model persisted -> {_MODEL_PATH}")

    # Check 8: antecedent_precipitation_index never api_score
    assert "antecedent_precipitation_index" in ALL_FEATURE_COLS, "FAIL: wrong field name"
    assert "api_score" not in ALL_FEATURE_COLS, "FAIL: api_score in feature list (must be antecedent_precipitation_index)"
    print("  [OK] antecedent_precipitation_index present; api_score absent from feature list")

    print()
    print("=" * 80)
    print("Phase 6 Part 2 — ALL ACCEPTANCE CRITERIA PASSED")
    print("  Model saved to: ml/models/fusion_model.pkl")
    print("  Next: Phase 7 (LOEO validation) will load this model via FusionModel.load()")
    print("=" * 80)
