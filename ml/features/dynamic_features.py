"""
dynamic_features.py — Dynamic (hazard) feature computation per hex per ingestion cycle.

Implements: SRS.md Section 9 (dynamic features) + Section 10.1 (FS integration),
            Phase 6 Part 1.
Owner: Guhan-10 (Phase 6)

WHAT THIS COMPUTES
------------------
All 14 dynamic hazard features listed in SRS.md Section 9, for one hex at one
ingestion cycle (or one historical snapshot for training):

  rainfall_1h, rainfall_3h, rainfall_6h, rainfall_24h, rainfall_72h_antecedent,
  rain_intensity_mm_hr, antecedent_precipitation_index,
  soil_saturation_ratio,
  factor_of_safety, factor_of_safety_min, factor_of_safety_max,
  simulated_ffgs_signal, simulated_gsi_signal,
  iot_anomaly_flag

TWO USAGE MODES
---------------
1. TRAINING (fill_dynamic_features_into_samples):
   Load Phase 4's event_centered_samples.parquet, backfill the None columns above,
   and return the enriched DataFrame ready for XGBoost training.

2. LIVE INFERENCE (compute_dynamic_features):
   Given a hex_id, its static features, and the latest ingested observations,
   return a dict of all 14 features for the Phase 8 risk-computation loop.

PHASE 5 DEPENDENCY
------------------
factor_of_safety.py (Phase 5, ml/models/factor_of_safety.py) is imported for FS
computation. If it does not exist yet (Phase 5 not merged), a loud warning is printed
and FS features are set to None — training will proceed but FS columns will be NaN
(XGBoost handles NaN natively; the model will simply not use those features until
Phase 5 is available). Re-run fill_dynamic_features_into_samples after Phase 5 merges
to get real FS values.

SIMULATED SIGNAL FEATURES (SRS.md Section 9)
---------------------------------------------
simulated_ffgs_signal: proxy for SAsiaFFGS guidance -- simple rainfall-threshold rule.
simulated_gsi_signal:  proxy for GSI RLFS guidance -- rainfall x susceptibility class.
Both are clearly labeled SIMULATED in code comments and output. They are NOT real
institutional integrations (SRS.md Section 3.2, CLAUDE.md).

HARD CONSTRAINTS (CLAUDE.md)
-----------------------------
- Feature named antecedent_precipitation_index -- NEVER api_score.
- soil_saturation_ratio = GWETROOT directly (SRS.md Section 10.1, frozen formula).
- XGBoost only -- this module does not train models, but output must be XGBoost-compatible.
- iot_anomaly_flag: stub returning False until Phase 8's /ingest/iot populates timestamps.
"""

import json
import math
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parents[2]
DATA_DIR    = REPO_ROOT / "data"
EVENTS_DIR  = DATA_DIR / "events"
TERRAIN_DIR = DATA_DIR / "terrain"

SAMPLES_PARQUET       = EVENTS_DIR / "event_centered_samples.parquet"
STATIC_FEATURES_JSON  = TERRAIN_DIR / "static_features.json"   # Phase 3 side-output

# ---------------------------------------------------------------------------
# Phase 5 import -- graceful fallback if not yet merged
# ---------------------------------------------------------------------------
_FS_AVAILABLE = False
try:
    from ml.models.factor_of_safety import compute_fs_band   # Phase 5 deliverable
    _FS_AVAILABLE = True
except ImportError:
    warnings.warn(
        "\n[dynamic_features] WARNING: ml.models.factor_of_safety not found.\n"
        "  Phase 5 (factor_of_safety.py) has not been merged yet.\n"
        "  factor_of_safety / factor_of_safety_min / factor_of_safety_max will be NaN.\n"
        "  Re-run fill_dynamic_features_into_samples() after Phase 5 merges.",
        stacklevel=2,
    )


# ---------------------------------------------------------------------------
# Factor of Safety soil parameters
# Source: Mundakkai-Chooralmala Scientific Reports paper (SRS.md Section 18, ref 1)
# Supplemented with Kerala laterite literature ranges for min/max band.
# ---------------------------------------------------------------------------
FS_PARAMS = {
    # Central (paper's measured values)
    "c_prime_central":   8.5,    # cohesion, kPa
    "phi_prime_central": 30.0,   # friction angle, degrees
    "z_central":         2.0,    # failure-plane depth, m
    "gamma_central":     18.0,   # unit weight, kN/m3
    "gamma_w":           9.81,   # water unit weight, kN/m3 (constant)
    # Worst-case combination (lowest strength, highest weight -- gives FS_min)
    "c_prime_worst":     4.0,
    "phi_prime_worst":   24.0,
    "z_worst":           3.0,
    "gamma_worst":       20.0,
    # Best-case combination (highest strength, lowest weight -- gives FS_max)
    "c_prime_best":      14.0,
    "phi_prime_best":    36.0,
    "z_best":            1.5,
    "gamma_best":        16.5,
}

# ---------------------------------------------------------------------------
# Simulated FFGS signal thresholds (SIMULATED proxy -- SRS.md Section 9)
# Calibrated against Kolathayar et al. (SRS.md Section 18, ref 3):
# July 2024 event saw ~50mm/3h peak at Chooralmala gauge.
# Threshold set at 45mm/3h so signal saturates clearly at event-time snapshots.
# ---------------------------------------------------------------------------
FFGS_THRESHOLD_3H_MM = 45.0   # mm/3h -> signal = 1.0 at this accumulation (SIMULATED)

# ---------------------------------------------------------------------------
# Simulated GSI signal thresholds (SIMULATED proxy -- SRS.md Section 9)
# 24h threshold: set at 40mm/24h so moderate events register a non-zero signal.
# Kolathayar et al. report ~350mm/24h for July 2024; threshold is deliberately low
# to give the model signal across the full training set, not just extreme events.
# ---------------------------------------------------------------------------
GSI_CLASS_WEIGHTS: dict[str, float] = {
    "Low":       0.10,
    "Moderate":  0.30,
    "High":      0.70,
    "Very High": 1.00,
}
GSI_RAIN_THRESHOLD_24H_MM = 40.0   # mm/24h (SIMULATED)

# GSI class ordinal encoding for XGBoost (ordered: Low < Moderate < High < Very High)
# These classes ARE ordered -- ordinal encoding is correct here.
GSI_CLASS_TO_INT: dict[str, int] = {
    "Low":       0,
    "Moderate":  1,
    "High":      2,
    "Very High": 3,
}

# IoT staleness threshold
IOT_STALENESS_THRESHOLD_SEC = 300   # 5 minutes without a message -> anomaly flag

# Antecedent Precipitation Index decay -- must match Phase 4's value (0.85)
API_DECAY = 0.85


# ===========================================================================
# Core feature computation -- single hex, single timestamp
# ===========================================================================

def compute_rainfall_windows(
    rainfall_series: list,
    series_end_idx: int,
) -> dict:
    """
    Compute rolling rainfall accumulation windows ending at series_end_idx.

    Args:
        rainfall_series: hourly rainfall values (mm), oldest first.
        series_end_idx:  index of current timestep (exclusive upper bound).

    Returns dict with rainfall_1h/3h/6h/24h/72h_antecedent and rain_intensity_mm_hr.
    """
    def _sum(window: int) -> Optional[float]:
        start = max(0, series_end_idx - window)
        vals = [v for v in rainfall_series[start:series_end_idx] if v is not None]
        return round(sum(vals), 4) if vals else None

    r1h = _sum(1)
    return {
        "rainfall_1h":             r1h,
        "rainfall_3h":             _sum(3),
        "rainfall_6h":             _sum(6),
        "rainfall_24h":            _sum(24),
        "rainfall_72h_antecedent": _sum(72),
        # rain_intensity_mm_hr: 1h accumulation = mm/hr at hourly resolution
        "rain_intensity_mm_hr":    r1h,
    }


def compute_api(
    rainfall_series: list,
    decay: float = API_DECAY,
) -> list:
    """
    Exponentially-decayed Antecedent Precipitation Index over hourly series.

    antecedent_precipitation_index -- NEVER api_score (CLAUDE.md / SRS.md Section 9).
    Decay=0.85 matches Phase 4's event_centered_sampling.py -- do not change independently.
    """
    running = 0.0
    result: list = []
    for p in rainfall_series:
        if p is None:
            result.append(None)
        else:
            running = decay * running + p
            result.append(round(running, 4))
    return result


def compute_factor_of_safety(
    slope_deg: Optional[float],
    soil_saturation_ratio: Optional[float],
) -> tuple:
    """
    Compute (factor_of_safety, factor_of_safety_min, factor_of_safety_max).

    Delegates to ml.models.factor_of_safety.compute_fs_band (Phase 5).
    Returns (None, None, None) with a warning if Phase 5 is not yet merged.

    soil_saturation_ratio = GWETROOT directly (SRS.md Section 10.1, frozen formula).
    """
    if slope_deg is None or soil_saturation_ratio is None:
        return None, None, None

    if not _FS_AVAILABLE:
        return None, None, None

    try:
        fs, fs_min, fs_max = compute_fs_band(
            slope_deg=slope_deg,
            soil_saturation_ratio=float(soil_saturation_ratio),
            params=FS_PARAMS,
        )
        return (
            round(float(fs),     4),
            round(float(fs_min), 4),
            round(float(fs_max), 4),
        )
    except Exception as exc:
        warnings.warn(
            f"[dynamic_features] compute_fs_band raised {type(exc).__name__}: {exc}\n"
            "  FS features set to None for this row.",
            stacklevel=2,
        )
        return None, None, None


def compute_fs_band_width_penalty(
    fs_min: Optional[float],
    fs_max: Optional[float],
) -> float:
    """
    FS band-width penalty for the confidence_score formula (SRS.md Section 10.3).

    confidence_score = 100 x model_class_probability x (1 - fs_band_width_penalty)

    Returns 0.0 if the FS band does not straddle 1.0 (failure threshold).
    Rises linearly toward 0.3 as the band widens across 1.0.
    """
    if fs_min is None or fs_max is None:
        return 0.0
    band_width = fs_max - fs_min
    straddles_failure = (fs_min < 1.0) and (fs_max > 1.0)
    if not straddles_failure:
        return 0.0
    # Reaches 0.3 when band_width >= 1.0 (very uncertain physics)
    return float(min(0.3, (band_width / 1.0) * 0.3))


def compute_simulated_ffgs_signal(rainfall_3h: Optional[float]) -> float:
    """
    SIMULATED proxy for SAsiaFFGS flash-flood guidance signal (SRS.md Section 9).
    NOT a real institutional integration (SRS.md Section 3.2, CLAUDE.md).

    Linear scale of rainfall_3h against FFGS_THRESHOLD_3H_MM, capped at 1.0.
    """
    if rainfall_3h is None:
        return 0.0
    return float(min(1.0, rainfall_3h / FFGS_THRESHOLD_3H_MM))


def compute_simulated_gsi_signal(
    gsi_susceptibility_class: Optional[str],
    rainfall_24h: Optional[float],
) -> float:
    """
    SIMULATED proxy for GSI RLFS landslide guidance signal (SRS.md Section 9).
    NOT a real institutional integration (SRS.md Section 3.2, CLAUDE.md).

    Rule: susceptibility class weight x rainfall_24h factor.
    """
    weight = GSI_CLASS_WEIGHTS.get(gsi_susceptibility_class or "Low", 0.10)
    rain_factor = float(min(1.0, (rainfall_24h or 0.0) / GSI_RAIN_THRESHOLD_24H_MM))
    return round(weight * rain_factor, 4)


def compute_iot_anomaly_flag(
    last_iot_timestamp: Optional[datetime],
    current_cycle_time: Optional[datetime] = None,
) -> bool:
    """
    IoT sensor health flag -- True if the most recent reading for this hex is stale.

    STUB: returns False when last_iot_timestamp is None (no IoT device on this hex).
    Phase 8's POST /ingest/iot populates last_iot_timestamp per device; when a device
    stops sending, Phase 6's live inference path detects staleness here and sets
    iot_anomaly_flag = True, which triggers the 'external-data-only estimate' label
    in Phase 12's dashboard (SRS.md Section 16 frozen wording).
    """
    if last_iot_timestamp is None:
        return False
    if current_cycle_time is None:
        current_cycle_time = datetime.now(timezone.utc)
    if last_iot_timestamp.tzinfo is None:
        last_iot_timestamp = last_iot_timestamp.replace(tzinfo=timezone.utc)
    age_sec = (current_cycle_time - last_iot_timestamp).total_seconds()
    return age_sec > IOT_STALENESS_THRESHOLD_SEC


# ===========================================================================
# High-level interface: single hex, single cycle (live inference mode)
# ===========================================================================

def compute_dynamic_features(
    hex_id: str,
    static_features: dict,
    rainfall_series_72h: list,
    soil_saturation_ratio: Optional[float],
    last_iot_timestamp: Optional[datetime] = None,
    current_cycle_time: Optional[datetime] = None,
) -> dict:
    """
    Compute all 14 dynamic hazard features for one hex at one ingestion cycle.

    Used by Phase 8's risk-computation loop (live inference). For training,
    use fill_dynamic_features_into_samples() instead.

    Args:
        hex_id:               H3 hex identifier.
        static_features:      dict from hexes.static_features JSONB (Phase 3 output).
        rainfall_series_72h:  list of hourly rainfall values (mm), oldest first,
                              length >= 72. Last element is the current hour.
        soil_saturation_ratio: GWETROOT value 0-1 (SRS.md Section 10.1 frozen formula).
                              UI must label this 'soil saturation proxy' -- never
                              'village-level measurement' (CLAUDE.md).
        last_iot_timestamp:   most recent IoT message time for this hex (from Phase 8).
        current_cycle_time:   ingestion cycle time (defaults to UTC now).

    Returns:
        dict of all 14 dynamic feature values, keyed by SRS.md Section 9 field names.
    """
    if current_cycle_time is None:
        current_cycle_time = datetime.now(timezone.utc)

    n = len(rainfall_series_72h)
    windows = compute_rainfall_windows(rainfall_series_72h, series_end_idx=n)

    # antecedent_precipitation_index -- NEVER api_score (CLAUDE.md / SRS.md Section 9)
    api_series = compute_api(rainfall_series_72h)
    antecedent_precipitation_index = api_series[-1] if api_series else None

    slope_deg = _safe_float(static_features.get("slope_deg"))
    fs, fs_min, fs_max = compute_factor_of_safety(slope_deg, soil_saturation_ratio)

    # Simulated signals -- SIMULATED, not real institutional integrations
    simulated_ffgs_signal = compute_simulated_ffgs_signal(windows["rainfall_3h"])
    simulated_gsi_signal  = compute_simulated_gsi_signal(
        gsi_susceptibility_class=static_features.get("gsi_susceptibility_class"),
        rainfall_24h=windows["rainfall_24h"],
    )

    iot_anomaly_flag = compute_iot_anomaly_flag(last_iot_timestamp, current_cycle_time)

    return {
        "rainfall_1h":                    windows["rainfall_1h"],
        "rainfall_3h":                    windows["rainfall_3h"],
        "rainfall_6h":                    windows["rainfall_6h"],
        "rainfall_24h":                   windows["rainfall_24h"],
        "rainfall_72h_antecedent":        windows["rainfall_72h_antecedent"],
        "rain_intensity_mm_hr":           windows["rain_intensity_mm_hr"],
        # antecedent_precipitation_index -- NEVER api_score
        "antecedent_precipitation_index": antecedent_precipitation_index,
        # soil_saturation_ratio = GWETROOT directly (SRS.md Section 10.1 frozen)
        "soil_saturation_ratio":          soil_saturation_ratio,
        # Factor of Safety (None until Phase 5 merges)
        "factor_of_safety":               fs,
        "factor_of_safety_min":           fs_min,
        "factor_of_safety_max":           fs_max,
        # SIMULATED proxy signals (not real GSI/FFGS integrations)
        "simulated_ffgs_signal":          simulated_ffgs_signal,
        "simulated_gsi_signal":           simulated_gsi_signal,
        # IoT anomaly (stub -- False until Phase 8 + Phase 10 wired)
        "iot_anomaly_flag":               iot_anomaly_flag,
    }


# ===========================================================================
# Training mode: fill None columns in Phase 4's parquet
# ===========================================================================

def load_static_features() -> dict:
    """
    Load static features for all pilot hexes.

    Primary: data/terrain/static_features.json (Phase 3 side-output).
    Fallback: Phase 8's PostGIS hexes table (requires DATABASE_URL env var).
    Fails loudly with a warning if neither is available (per CLAUDE.md --
    never silently substitute fake data).
    """
    if STATIC_FEATURES_JSON.exists():
        with open(STATIC_FEATURES_JSON) as f:
            data = json.load(f)
        if isinstance(data, list):
            return {row["hex_id"]: row for row in data}
        return data

    db_url = _get_db_url()
    if db_url:
        return _load_static_features_from_db(db_url)

    warnings.warn(
        f"\n[dynamic_features] WARNING: {STATIC_FEATURES_JSON} not found and no DATABASE_URL set.\n"
        "  Run ml/features/static_features.py (Phase 3) and ensure it exports\n"
        "  data/terrain/static_features.json, or set DATABASE_URL env var.\n"
        "  Static feature columns (slope_deg, TWI, etc.) will be NaN in training.",
        stacklevel=2,
    )
    return {}


def _get_db_url() -> Optional[str]:
    import os
    return os.environ.get("DATABASE_URL")


def _load_static_features_from_db(db_url: str) -> dict:
    try:
        import sqlalchemy
        engine = sqlalchemy.create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                sqlalchemy.text("SELECT hex_id, static_features FROM hexes")
            ).fetchall()
        result = {}
        for hex_id, sf in rows:
            if isinstance(sf, str):
                sf = json.loads(sf)
            result[hex_id] = sf or {}
        print(f"[dynamic_features] Loaded static features for {len(result)} hexes from DB.")
        return result
    except Exception as exc:
        warnings.warn(
            f"[dynamic_features] DB static feature load failed: {exc}\n"
            "  Static columns will be NaN.",
            stacklevel=2,
        )
        return {}


def fill_dynamic_features_into_samples(
    samples_path: Path = SAMPLES_PARQUET,
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Load Phase 4's event_centered_samples.parquet and backfill all None dynamic
    and static feature columns. Returns the enriched DataFrame for XGBoost training.

    Fills (all currently None in Phase 4 output):
      - All 11 static columns (slope_deg, aspect, TWI, TRI, elevation,
        distance_to_stream_m, drainage_density, land_use_class, ndvi_mean,
        historical_event_count_500m, gsi_susceptibility_class)
      - gsi_susceptibility_class_int   (ordinal 0-3 encoding for XGBoost)
      - factor_of_safety / _min / _max (Phase 5; NaN if not merged)
      - fs_band_width_penalty           (for confidence_score in Part 2)
      - simulated_ffgs_signal           (rainfall-threshold rule)
      - simulated_gsi_signal            (rainfall x GSI class)
      - iot_anomaly_flag                (False -- stub for historical snapshots)

    Does NOT overwrite Phase 4's already-seeded values (rainfall windows,
    antecedent_precipitation_index, soil_saturation_ratio) -- validates them instead.

    Args:
        samples_path: Phase 4 parquet path.
        output_path:  save destination (defaults to overwriting samples_path in-place).

    Returns: enriched pd.DataFrame ready for train_fusion_model.py.
    """
    if not samples_path.exists():
        print(
            f"ERROR: {samples_path} not found.\n"
            "  Run ml/features/event_centered_sampling.py (Phase 4) first.",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_parquet(samples_path)
    print(f"[dynamic_features] Loaded {len(df)} rows from {samples_path}")
    _validate_phase4_columns(df)

    # -------------------------------------------------------------------------
    # 1. Join static features (Phase 3)
    # -------------------------------------------------------------------------
    static_map = load_static_features()
    static_cols = [
        "slope_deg", "aspect", "TWI", "TRI", "elevation",
        "distance_to_stream_m", "drainage_density",
        "land_use_class", "ndvi_mean",
        "historical_event_count_500m", "gsi_susceptibility_class",
    ]
    if static_map:
        static_df = pd.DataFrame.from_dict(static_map, orient="index")
        static_df.index.name = "hex_id"
        static_df = static_df.reset_index()
        available = [c for c in static_cols if c in static_df.columns]
        df = df.drop(columns=available, errors="ignore")
        df = df.merge(static_df[["hex_id"] + available], on="hex_id", how="left")
        print(
            f"[dynamic_features] Joined static features: "
            f"{static_df['hex_id'].nunique()} hexes, {len(available)} columns"
        )
    else:
        print("[dynamic_features] No static features available -- columns will be NaN.")

    # -------------------------------------------------------------------------
    # 2. Ordinal-encode gsi_susceptibility_class (Low=0 ... Very High=3)
    # -------------------------------------------------------------------------
    df["gsi_susceptibility_class_int"] = (
        df["gsi_susceptibility_class"]
        .map(GSI_CLASS_TO_INT)
        .where(df["gsi_susceptibility_class"].notna())
        .astype("float32")
    )

    # -------------------------------------------------------------------------
    # 3. Factor of Safety (per row via Phase 5 -- NaN if Phase 5 not merged)
    # -------------------------------------------------------------------------
    if not _FS_AVAILABLE:
        print("[dynamic_features] Phase 5 not merged -- FS columns will be NaN.")
        df["factor_of_safety"]     = np.nan
        df["factor_of_safety_min"] = np.nan
        df["factor_of_safety_max"] = np.nan
    else:
        print(f"[dynamic_features] Computing FS for {len(df)} rows (Phase 5 available) ...")
        fs_results = df.apply(
            lambda row: pd.Series(
                compute_factor_of_safety(
                    slope_deg=_safe_float(row.get("slope_deg")),
                    soil_saturation_ratio=_safe_float(row.get("soil_saturation_ratio")),
                ),
                index=["factor_of_safety", "factor_of_safety_min", "factor_of_safety_max"],
            ),
            axis=1,
        )
        df["factor_of_safety"]     = fs_results["factor_of_safety"]
        df["factor_of_safety_min"] = fs_results["factor_of_safety_min"]
        df["factor_of_safety_max"] = fs_results["factor_of_safety_max"]

    # -------------------------------------------------------------------------
    # 4. FS band-width penalty (used by train_fusion_model.py for confidence_score)
    # -------------------------------------------------------------------------
    df["fs_band_width_penalty"] = df.apply(
        lambda row: compute_fs_band_width_penalty(
            _safe_float(row.get("factor_of_safety_min")),
            _safe_float(row.get("factor_of_safety_max")),
        ),
        axis=1,
    ).astype("float32")

    # -------------------------------------------------------------------------
    # 5. Simulated FFGS signal (SIMULATED -- not a real integration)
    # -------------------------------------------------------------------------
    df["simulated_ffgs_signal"] = df["rainfall_3h"].apply(
        lambda r: compute_simulated_ffgs_signal(_safe_float(r))
    ).astype("float32")

    # -------------------------------------------------------------------------
    # 6. Simulated GSI signal (SIMULATED -- not a real integration)
    # -------------------------------------------------------------------------
    df["simulated_gsi_signal"] = df.apply(
        lambda row: compute_simulated_gsi_signal(
            gsi_susceptibility_class=row.get("gsi_susceptibility_class"),
            rainfall_24h=_safe_float(row.get("rainfall_24h")),
        ),
        axis=1,
    ).astype("float32")

    # -------------------------------------------------------------------------
    # 7. IoT anomaly flag -- False for all historical training rows
    #    (these snapshots predate Phase 10's IoT data)
    # -------------------------------------------------------------------------
    df["iot_anomaly_flag"] = False

    # -------------------------------------------------------------------------
    # 8. land_use_class: ensure numeric (ESA WorldCover codes are nominal ints)
    #    XGBoost will treat these as categorical features via enable_categorical=True
    # -------------------------------------------------------------------------
    if "land_use_class" in df.columns:
        df["land_use_class"] = pd.to_numeric(df["land_use_class"], errors="coerce")

    # -------------------------------------------------------------------------
    # 9. Validate null rates
    # -------------------------------------------------------------------------
    _validate_enriched_samples(df)

    # -------------------------------------------------------------------------
    # 10. Save
    # -------------------------------------------------------------------------
    save_path = output_path or samples_path
    df.to_parquet(save_path, index=False)
    print(f"\n[dynamic_features] Enriched parquet saved -> {save_path}")
    print(f"  Rows: {len(df)}  |  Columns: {len(df.columns)}")
    if not _FS_AVAILABLE:
        print("  *** Re-run after Phase 5 merges to populate FS columns. ***")
    return df


# ===========================================================================
# Helpers
# ===========================================================================

def _safe_float(val) -> Optional[float]:
    """Convert to float, returning None for NaN/None/non-numeric."""
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _validate_phase4_columns(df: pd.DataFrame) -> None:
    """Verify Phase 4's expected columns exist and log coverage warnings."""
    required = [
        "hex_id", "snapshot_timestamp", "tier", "tier_int", "sample_type",
        "rainfall_1h", "antecedent_precipitation_index", "soil_saturation_ratio",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(
            f"ERROR: Phase 4 parquet missing expected columns: {missing}\n"
            "  Re-run event_centered_sampling.py (Phase 4).",
            file=sys.stderr,
        )
        sys.exit(1)

    for col in ["rainfall_1h", "soil_saturation_ratio", "antecedent_precipitation_index"]:
        if col in df.columns:
            pct_null = df[col].isna().mean() * 100
            if pct_null > 50:
                print(
                    f"  WARNING: {col} is {pct_null:.0f}% null -- "
                    "did Phase 1 (ingest_rainfall/soil) complete?",
                    file=sys.stderr,
                )


def _validate_enriched_samples(df: pd.DataFrame) -> None:
    """Log null-rate summary for key features after enrichment."""
    key_features = [
        "slope_deg", "soil_saturation_ratio", "factor_of_safety",
        "simulated_ffgs_signal", "simulated_gsi_signal",
        "antecedent_precipitation_index", "gsi_susceptibility_class_int",
    ]
    print("\n[dynamic_features] Null-rate summary (key features):")
    for feat in key_features:
        if feat in df.columns:
            pct = df[feat].isna().mean() * 100
            flag = "  *** HIGH ***" if pct > 30 else ""
            print(f"  {feat:42s}  {pct:5.1f}% null{flag}")


# ===========================================================================
# CLI entry point
# ===========================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6 Part 1: fill dynamic features into Phase 4's training parquet."
    )
    parser.add_argument(
        "--input", type=Path, default=SAMPLES_PARQUET,
        help=f"Input parquet (default: {SAMPLES_PARQUET})",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output path (default: overwrites input in-place)",
    )
    args = parser.parse_args()

    print("=" * 65)
    print("HydraSense -- Phase 6 Part 1: Dynamic Feature Engineering")
    print("SRS.md Section 9 + Section 10.1")
    print("=" * 65)

    enriched = fill_dynamic_features_into_samples(
        samples_path=args.input,
        output_path=args.output,
    )

    preview_cols = [
        "hex_id", "tier", "rainfall_1h", "rainfall_24h",
        "antecedent_precipitation_index", "soil_saturation_ratio",
        "factor_of_safety", "simulated_ffgs_signal", "simulated_gsi_signal",
        "iot_anomaly_flag",
    ]
    print("\nTop-5 rows (key dynamic columns):")
    print(enriched[[c for c in preview_cols if c in enriched.columns]].head().to_string())
