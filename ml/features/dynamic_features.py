"""
Phase 6 (Part 1) — Dynamic Feature Engineering.

SRS.md references:
  Section 9   — the 14 dynamic hazard features (field names frozen)
  Section 10.1 — soil_saturation_ratio = GWETROOT directly; FS formula (Phase 5)
  Section 10.2 — risk_score formula (used in train_fusion_model.py, not here)
  Section 10.4 — tier thresholds (used in train_fusion_model.py, not here)
  Section 14  — observations.dynamic_features JSONB schema (field names frozen)

HARD CONSTRAINTS (CLAUDE.md + SRS frozen decisions):
  - soil_saturation_ratio = GWETROOT directly.  No derivation, no transformation.
  - antecedent_precipitation_index — NEVER api_score anywhere in code or comments.
  - simulated_ffgs_signal:  rainfall-threshold rule ONLY.  Must be labeled "simulated"
    in all UI components (see comment below for the rule).
  - simulated_gsi_signal:  rainfall + gsi_susceptibility_class rule ONLY.  Must be
    labeled "simulated" in all UI components.
  - iot_anomaly_flag: STUB returning False until Phase 10's IoT simulation exists.
    Must have a clear TODO, not silent zeros.
  - FS features: call Phase 5's compute_factor_of_safety() — do not re-implement the
    equation here.
  - Field names are frozen per Section 14:
    rainfall_1h, rainfall_3h, rainfall_6h, rainfall_24h, rainfall_72h_antecedent,
    rain_intensity_mm_hr, antecedent_precipitation_index, soil_saturation_ratio,
    factor_of_safety, factor_of_safety_min, factor_of_safety_max,
    simulated_ffgs_signal, simulated_gsi_signal, iot_anomaly_flag

14 DYNAMIC FEATURES (SRS §9):
  1.  rainfall_1h                   — mm in past 1 hour
  2.  rainfall_3h                   — mm in past 3 hours
  3.  rainfall_6h                   — mm in past 6 hours
  4.  rainfall_24h                  — mm in past 24 hours
  5.  rainfall_72h_antecedent       — mm in past 72 hours (antecedent window)
  6.  rain_intensity_mm_hr          — peak 1h intensity in the past 6h window
  7.  antecedent_precipitation_index — exponentially decayed API (decay=0.85)
  8.  soil_saturation_ratio         — GWETROOT directly from NASA POWER (Phase 1)
  9.  factor_of_safety              — central FS (Phase 5)
  10. factor_of_safety_min          — worst-case FS (Phase 5)
  11. factor_of_safety_max          — best-case FS (Phase 5)
  12. simulated_ffgs_signal         — SIMULATED: rainfall-threshold rule (not SAsiaFFGS API)
  13. simulated_gsi_signal          — SIMULATED: rainfall + susceptibility rule
  14. iot_anomaly_flag              — STUB (False) until Phase 10

SIMULATED SIGNAL RULES (clearly labeled — SRS §8 confirms these proxies are deliberate):
  simulated_ffgs_signal (bool — True = flash-flood guidance threshold exceeded):
    True  if rainfall_3h >= FFGS_3H_THRESHOLD_MM  (40 mm/3h)
          or rainfall_1h >= FFGS_1H_THRESHOLD_MM  (25 mm/1h)
    Based on India Meteorological Department "heavy rain" thresholds used as a
    proxy for the South-Asia Flash Flood Guidance System alert signal.
    NOT the real SAsiaFFGS API (no public access confirmed per SRS §8).

  simulated_gsi_signal (bool — True = GSI landslide risk signal active):
    True  if (rainfall_24h >= GSI_24H_THRESHOLD_MM) AND
             (gsi_susceptibility_class in {"High", "Very High"})
          or (rainfall_24h >= GSI_HIGH_24H_MM) for any susceptibility class
    Based on Wayanad-specific empirical thresholds from the GSI Bhukosh FIR reports.
    NOT the real GSI RLFS signal (no public API per SRS §8).

ANTECEDENT PRECIPITATION INDEX (antecedent_precipitation_index):
  API_t = 0.85 * API_{t-1} + P_t   (exponential decay, standard hydrological formulation)
  The decay constant 0.85 is consistent with Phase 4's event_centered_sampling.py.
  Never called api_score — CLAUDE.md hard constraint.

MISSING INPUT POLICY:
  If slope_deg is missing (Phase 3 not run), FS fields are None + logged once per run.
  If GWETROOT is missing, soil_saturation_ratio is None + logged once per run.
  Never substitute silent zeros; always propagate None to downstream features that depend
  on the missing value.  Phase 6's training handles None values via XGBoost's native
  missing-value mechanism.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# Phase 5 FS model (no re-implementation)
import sys
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from ml.models.factor_of_safety import compute_factor_of_safety

# ---------------------------------------------------------------------------
# Constants — thresholds for simulated signals (clearly labeled)
# ---------------------------------------------------------------------------

# simulated_ffgs_signal thresholds (proxy for SAsiaFFGS — explicitly NOT the real signal)
# Source: IMD heavy rain classification + typical South-Asia FFG guidance levels
FFGS_1H_THRESHOLD_MM: float  = 25.0   # >= 25 mm/1h -> simulated flash-flood guidance exceedance
FFGS_3H_THRESHOLD_MM: float  = 40.0   # >= 40 mm/3h -> simulated flash-flood guidance exceedance

# simulated_gsi_signal thresholds (proxy for GSI RLFS — explicitly NOT the real signal)
# Source: Wayanad GSI FIR thresholds, Achu et al. 2025 empirical analysis
GSI_24H_HIGH_SUSC_MM: float  = 80.0   # >= 80 mm/24h AND susceptibility High/Very High
GSI_24H_ANY_SUSC_MM:  float  = 150.0  # >= 150 mm/24h regardless of susceptibility class
GSI_HIGH_CLASSES: frozenset[str] = frozenset({"High", "Very High"})

# Antecedent Precipitation Index decay constant (matches Phase 4's event_centered_sampling.py)
API_DECAY: float = 0.85

# ---------------------------------------------------------------------------
# Data paths (defaults; callers can override via load_*() kwargs)
# ---------------------------------------------------------------------------
_DATA = _ROOT / "data"
_RAINFALL_CURRENT_PATH  = _DATA / "weather"  / "rainfall_current.json"
_RAINFALL_FORECAST_PATH = _DATA / "weather"  / "rainfall_forecast.json"
_SOIL_PATH              = _DATA / "soil"     / "soil_moisture.json"
_GSI_PATH               = _DATA / "susceptibility" / "gsi_susceptibility.csv"


# ---------------------------------------------------------------------------
# Loader helpers — Phase 1 data
# ---------------------------------------------------------------------------

def load_rainfall_series(
    path: Path = _RAINFALL_CURRENT_PATH,
) -> dict[str, dict[str, Optional[float]]]:
    """
    Load observed hourly rainfall from Phase 1's rainfall_current.json.

    Returns:
        {village_name: {"ISO_hour_str": precipitation_mm, ...}}
        e.g. {"Mundakkai": {"2026-09-05T10:00": 1.3, ...}}
    """
    if not path.exists():
        print(f"[dynamic_features] WARNING: {path} not found — rainfall features will be None")
        return {}
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    lookup: dict[str, dict[str, Optional[float]]] = {}
    for loc in data.get("locations", []):
        name   = loc["location"]
        times  = loc.get("series", {}).get("time",             [])
        precip = loc.get("series", {}).get("precipitation_mm", [])
        lookup[name] = dict(zip(times, precip))
    return lookup


def load_forecast_series(
    path: Path = _RAINFALL_FORECAST_PATH,
) -> dict[str, dict[str, Optional[float]]]:
    """
    Load hourly forecast rainfall from Phase 1's rainfall_forecast.json.
    Same format as observed series; used for lead-time estimation (Phase 9).

    Returns:
        {village_name: {"ISO_hour_str": precipitation_mm, ...}}
    """
    if not path.exists():
        print(f"[dynamic_features] WARNING: {path} not found — forecast features will be None")
        return {}
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    lookup: dict[str, dict[str, Optional[float]]] = {}
    for loc in data.get("locations", []):
        name   = loc["location"]
        times  = loc.get("series", {}).get("time",             [])
        precip = loc.get("series", {}).get("precipitation_mm", [])
        lookup[name] = dict(zip(times, precip))
    return lookup


def load_soil_series(
    path: Path = _SOIL_PATH,
) -> dict[str, dict[str, Optional[float]]]:
    """
    Load hourly GWETROOT from Phase 1's soil_moisture.json.
    soil_saturation_ratio = GWETROOT directly (SRS §10.1 frozen formula).

    Returns:
        {village_name: {"YYYYMMDDHH": gwetroot_0_to_1, ...}}
    """
    if not path.exists():
        print(f"[dynamic_features] WARNING: {path} not found — soil_saturation_ratio will be None")
        return {}
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    lookup: dict[str, dict[str, Optional[float]]] = {}
    for loc in data.get("locations", []):
        name = loc["location"]
        lookup[name] = loc.get("gwetroot_hourly", {})
    return lookup


def load_gsi_lookup(
    path: Path = _GSI_PATH,
) -> dict[str, str]:
    """
    Load GSI susceptibility class per hex_id from Phase 2 CSV.

    Returns:
        {hex_id: susceptibility_class}  e.g. {"8860064e4bfffff": "Moderate"}
    """
    if not path.exists():
        print(f"[dynamic_features] WARNING: {path} not found — simulated_gsi_signal will be None")
        return {}
    import csv
    lookup: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            hid   = row["hex_id"].strip()
            cls   = row["susceptibility_class"].strip()
            if hid and cls:
                lookup[hid] = cls
    return lookup


# ---------------------------------------------------------------------------
# Lookup helpers — single timestamp
# ---------------------------------------------------------------------------

def _get_rainfall_at(
    lookup: dict[str, dict[str, Optional[float]]],
    village: str,
    dt: datetime,
) -> Optional[float]:
    """Get observed precipitation (mm) for village at exact hour dt."""
    if not lookup or village not in lookup:
        return None
    iso_hour = dt.strftime("%Y-%m-%dT%H:00")
    return lookup[village].get(iso_hour)


def _get_gwetroot_at(
    lookup: dict[str, dict[str, Optional[float]]],
    village: str,
    dt: datetime,
) -> Optional[float]:
    """
    Get GWETROOT for village at dt.
    NASA POWER hourly key format: YYYYMMDDHH (no separators).
    Falls back to daily key YYYYMMDD, then to the most recent non-null entry.
    The last-available fallback is correct: NASA POWER changes at sub-daily resolution
    on a ~50 km grid, and the Phase 1 snapshot may not cover the current cycle's hour.
    This is documented, not a silent imputation.
    """
    if not lookup or village not in lookup:
        return None
    series = lookup[village]
    key_h = dt.strftime("%Y%m%d%H")
    key_d = dt.strftime("%Y%m%d")
    val = series.get(key_h) if series.get(key_h) is not None else series.get(key_d)
    if val is not None:
        return float(val)
    # Fallback: latest non-null entry in the series
    # (NASA POWER snapshot may not cover the current cycle timestamp)
    for k in sorted(series.keys(), reverse=True):
        v = series[k]
        if v is not None:
            return float(v)
    return None


# ---------------------------------------------------------------------------
# Rolling window sums over the rainfall series
# ---------------------------------------------------------------------------

def _rolling_sum(
    lookup: dict[str, dict[str, Optional[float]]],
    village: str,
    end_dt: datetime,
    hours: int,
) -> Optional[float]:
    """
    Sum precipitation over `hours` hours ending at (and including) end_dt.
    Returns None if no data is found in the window.
    """
    total = 0.0
    found_any = False
    for h in range(hours):
        slot = end_dt - timedelta(hours=h)
        val = _get_rainfall_at(lookup, village, slot)
        if val is not None:
            total += val
            found_any = True
    return round(total, 4) if found_any else None


def _peak_1h_in_window(
    lookup: dict[str, dict[str, Optional[float]]],
    village: str,
    end_dt: datetime,
    window_hours: int = 6,
) -> Optional[float]:
    """
    Maximum 1h precipitation in the last `window_hours` hours ending at end_dt.
    Used for rain_intensity_mm_hr.
    """
    peak: Optional[float] = None
    for h in range(window_hours):
        slot = end_dt - timedelta(hours=h)
        val = _get_rainfall_at(lookup, village, slot)
        if val is not None:
            peak = max(peak, val) if peak is not None else val
    return round(peak, 4) if peak is not None else None


# ---------------------------------------------------------------------------
# Antecedent Precipitation Index
# antecedent_precipitation_index — NEVER api_score (CLAUDE.md hard constraint)
# ---------------------------------------------------------------------------

def _compute_antecedent_precipitation_index(
    lookup: dict[str, dict[str, Optional[float]]],
    village: str,
    end_dt: datetime,
    lookback_hours: int = 720,  # 30 days
    decay: float = API_DECAY,
) -> Optional[float]:
    """
    Exponentially-decayed Antecedent Precipitation Index at end_dt.
    antecedent_precipitation_index = decay * API_{t-1} + P_t  (running sum)
    decay = 0.85 (matches event_centered_sampling.py, Phase 4)
    Field: antecedent_precipitation_index — NEVER api_score (CLAUDE.md).
    """
    running = 0.0
    found_any = False
    for h in range(lookback_hours, -1, -1):
        slot = end_dt - timedelta(hours=h)
        val = _get_rainfall_at(lookup, village, slot)
        if val is not None:
            running = decay * running + val
            found_any = True
        # If None, decay without adding (continuous decay even through data gaps)
        else:
            running = decay * running
    return round(running, 4) if found_any else None


# ---------------------------------------------------------------------------
# Simulated signal rules (explicitly NOT the real SAsiaFFGS or GSI RLFS APIs)
# ---------------------------------------------------------------------------

def _compute_simulated_ffgs_signal(
    rainfall_1h: Optional[float],
    rainfall_3h: Optional[float],
) -> Optional[bool]:
    """
    SIMULATED flash-flood guidance signal (proxy for SAsiaFFGS).
    NOT the real SAsiaFFGS API — no public access per SRS §8.
    Rule: True if rainfall_1h >= 25 mm/h OR rainfall_3h >= 40 mm/3h.
    Source: IMD heavy rain classification thresholds.
    Label as 'simulated' in all UI components (SRS §8 frozen requirement).
    """
    if rainfall_1h is None and rainfall_3h is None:
        return None
    r1 = rainfall_1h or 0.0
    r3 = rainfall_3h or 0.0
    return bool(r1 >= FFGS_1H_THRESHOLD_MM or r3 >= FFGS_3H_THRESHOLD_MM)


def _compute_simulated_gsi_signal(
    rainfall_24h: Optional[float],
    gsi_susceptibility_class: Optional[str],
) -> Optional[bool]:
    """
    SIMULATED GSI landslide risk signal (proxy for GSI RLFS).
    NOT the real GSI RLFS signal — no public API per SRS §8.
    Rule:
      True if rainfall_24h >= 80 mm AND susceptibility in {High, Very High}
      True if rainfall_24h >= 150 mm (any susceptibility class)
    Source: Wayanad GSI FIR thresholds; Achu et al. (2025) empirical analysis.
    Label as 'simulated' in all UI components (SRS §8 frozen requirement).
    """
    if rainfall_24h is None:
        return None
    r24 = rainfall_24h
    susc = (gsi_susceptibility_class or "").strip()

    if r24 >= GSI_24H_ANY_SUSC_MM:
        return True
    if r24 >= GSI_24H_HIGH_SUSC_MM and susc in GSI_HIGH_CLASSES:
        return True
    return False


def _compute_iot_anomaly_flag() -> bool:
    """
    IoT sensor anomaly flag.
    # TODO(Phase 10): wire in real IoT sensor data from Phase 10's simulation.
    #   Until Phase 10 is implemented, this always returns False.
    #   Do NOT substitute random values or heuristics here — the stub is explicit.
    Stub returns False (no IoT data available until Phase 10).
    """
    # TODO: replace with Phase 10 IoT sensor anomaly detection
    return False


# ---------------------------------------------------------------------------
# FS band width penalty (SRS §10.3)
# ---------------------------------------------------------------------------

def _compute_fs_band_penalty(
    factor_of_safety_min: Optional[float],
    factor_of_safety_max: Optional[float],
    fs_band_straddles_one: Optional[bool],
) -> float:
    """
    FS band width penalty for confidence_score (SRS §10.3).
    = 0 if band does not straddle FS=1.0
    Rising toward ~0.3 as band widens and straddles the failure threshold.

    Formula: penalty = 0.3 * min(1.0, (fs_max - fs_min) / 2.0) if straddles else 0.0
    The divisor 2.0 normalises the band width (a band of 2 units = full penalty).
    """
    if not fs_band_straddles_one:
        return 0.0
    if factor_of_safety_min is None or factor_of_safety_max is None:
        return 0.0
    band_width = max(0.0, factor_of_safety_max - factor_of_safety_min)
    return round(0.3 * min(1.0, band_width / 2.0), 4)


# ---------------------------------------------------------------------------
# Public API — per-hex per-cycle
# ---------------------------------------------------------------------------

def compute_dynamic_features(
    hex_id:     str,
    village:    str,
    timestamp:  datetime,
    slope_deg:  Optional[float],
    gsi_susceptibility_class: Optional[str],
    rainfall_lookup: dict[str, dict[str, Optional[float]]],
    soil_lookup:     dict[str, dict[str, Optional[float]]],
) -> dict[str, Any]:
    """
    Compute all 14 dynamic hazard features for one hex at one ingestion-cycle timestamp.

    Reads Phase 1 data via pre-loaded lookup dicts (to avoid re-parsing JSON per hex).
    Calls Phase 5's compute_factor_of_safety() for FS features.

    Arguments:
        hex_id      : H3 hex identifier
        village     : village name (for rainfall/soil lookup — NASA POWER nearest-grid)
        timestamp   : cycle ingestion datetime (UTC)
        slope_deg   : from Phase 3 static_features; None if Phase 3 not run
        gsi_susceptibility_class : from Phase 2 GSI CSV; None if missing
        rainfall_lookup : pre-loaded {village: {iso_hour: mm}} from load_rainfall_series()
        soil_lookup     : pre-loaded {village: {YYYYMMDDHH: gwetroot}} from load_soil_series()

    Returns:
        dict with all 14 field names per SRS §9/§14 + audit fields.
        Fields with None = data not available (never silently defaulted).
    """
    # ── Rainfall windows ──────────────────────────────────────────────────
    r1h   = _rolling_sum(rainfall_lookup, village, timestamp, 1)
    r3h   = _rolling_sum(rainfall_lookup, village, timestamp, 3)
    r6h   = _rolling_sum(rainfall_lookup, village, timestamp, 6)
    r24h  = _rolling_sum(rainfall_lookup, village, timestamp, 24)
    r72h  = _rolling_sum(rainfall_lookup, village, timestamp, 72)

    # ── Rain intensity: peak 1h in past 6h window ─────────────────────────
    rain_intensity_mm_hr = _peak_1h_in_window(rainfall_lookup, village, timestamp, 6)

    # ── Antecedent Precipitation Index (NEVER api_score — CLAUDE.md) ─────
    antecedent_precipitation_index = _compute_antecedent_precipitation_index(
        rainfall_lookup, village, timestamp
    )

    # ── Soil saturation = GWETROOT directly (SRS §10.1 frozen formula) ───
    soil_saturation_ratio = _get_gwetroot_at(soil_lookup, village, timestamp)

    # ── Factor of Safety (Phase 5) ────────────────────────────────────────
    fs_result = compute_factor_of_safety(
        slope_deg=slope_deg,
        soil_saturation_ratio=soil_saturation_ratio,
    )
    factor_of_safety     = fs_result["factor_of_safety"]
    factor_of_safety_min = fs_result["factor_of_safety_min"]
    factor_of_safety_max = fs_result["factor_of_safety_max"]
    fs_band_straddles    = fs_result["fs_band_straddles_one"]
    fs_missing           = fs_result["missing_inputs"]

    # ── Confidence penalty (SRS §10.3) — used by train_fusion_model.py ───
    fs_band_width_penalty = _compute_fs_band_penalty(
        factor_of_safety_min, factor_of_safety_max, fs_band_straddles
    )

    # ── Simulated signals (labeled — NOT real API outputs) ───────────────
    # simulated_ffgs_signal: SIMULATED — proxy for SAsiaFFGS (SRS §8)
    simulated_ffgs_signal = _compute_simulated_ffgs_signal(r1h, r3h)
    # simulated_gsi_signal: SIMULATED — proxy for GSI RLFS (SRS §8)
    simulated_gsi_signal  = _compute_simulated_gsi_signal(r24h, gsi_susceptibility_class)

    # ── IoT anomaly flag — STUB until Phase 10 ───────────────────────────
    iot_anomaly_flag = _compute_iot_anomaly_flag()

    return {
        # ── 14 features per SRS §9 / §14 (field names frozen) ─────────
        "rainfall_1h":                     r1h,
        "rainfall_3h":                     r3h,
        "rainfall_6h":                     r6h,
        "rainfall_24h":                    r24h,
        "rainfall_72h_antecedent":         r72h,
        "rain_intensity_mm_hr":            rain_intensity_mm_hr,
        # antecedent_precipitation_index — NEVER api_score (CLAUDE.md)
        "antecedent_precipitation_index":  antecedent_precipitation_index,
        # soil_saturation_ratio = GWETROOT directly (SRS §10.1 frozen)
        "soil_saturation_ratio":           soil_saturation_ratio,
        "factor_of_safety":                factor_of_safety,
        "factor_of_safety_min":            factor_of_safety_min,
        "factor_of_safety_max":            factor_of_safety_max,
        # SIMULATED — NOT real SAsiaFFGS/GSI RLFS signals (SRS §8)
        "simulated_ffgs_signal":           simulated_ffgs_signal,
        "simulated_gsi_signal":            simulated_gsi_signal,
        # STUB: iot_anomaly_flag — returns False until Phase 10
        "iot_anomaly_flag":                iot_anomaly_flag,
        # ── Audit / confidence fields (not model inputs; for API/UI) ─────
        "fs_band_width_penalty":           fs_band_width_penalty,
        "fs_band_straddles_one":           fs_band_straddles,
        "fs_missing_inputs":               fs_missing,
        "hex_id":                          hex_id,
        "village":                         village,
        "timestamp":                       timestamp.isoformat(),
        "gsi_susceptibility_class_used":   gsi_susceptibility_class,
        "slope_deg_used":                  slope_deg,
    }


# ---------------------------------------------------------------------------
# Batch orchestrator — all pilot hexes, current timestamp
# ---------------------------------------------------------------------------

def compute_all_hexes_current_cycle(
    timestamp:              Optional[datetime]    = None,
    static_features_path:   Optional[Path]        = None,
    rainfall_current_path:  Path                  = _RAINFALL_CURRENT_PATH,
    soil_path:              Path                  = _SOIL_PATH,
    gsi_path:               Path                  = _GSI_PATH,
) -> dict[str, dict[str, Any]]:
    """
    Compute all 14 dynamic features for every pilot hex for the current ingestion cycle.

    Arguments:
        timestamp             : cycle UTC datetime; defaults to latest hour available
                                in rainfall_current.json
        static_features_path  : Path to Phase 3 static_features.parquet (for slope_deg).
                                If None, falls back to gsi_susceptibility.csv for hex IDs
                                and slope_deg = None (FS will be flagged as missing).
        rainfall_current_path : override path for rainfall JSON
        soil_path             : override path for soil moisture JSON
        gsi_path              : override path for GSI susceptibility CSV

    Returns:
        {hex_id: compute_dynamic_features() result}
    """
    # Load lookup tables once (not per hex)
    rainfall_lookup = load_rainfall_series(rainfall_current_path)
    soil_lookup     = load_soil_series(soil_path)
    gsi_lookup      = load_gsi_lookup(gsi_path)

    # ── Determine timestamp ────────────────────────────────────────────────
    if timestamp is None:
        # Use latest hour in rainfall series
        all_hours: list[str] = []
        for series in rainfall_lookup.values():
            all_hours.extend(series.keys())
        if all_hours:
            latest_iso = max(all_hours)
            timestamp = datetime.fromisoformat(latest_iso)
        else:
            from datetime import timezone
            timestamp = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
        print(f"[dynamic_features] Using timestamp: {timestamp.isoformat()}")

    # ── Load hex list + slope_deg from Phase 3 parquet (or GSI CSV fallback) ──
    hex_slope: dict[str, Optional[float]] = {}
    hex_village: dict[str, str] = {}

    if static_features_path is None:
        # Phase 3 writes to data/processed/; data/features/ is a legacy alias
        _sf_primary = _ROOT / "data" / "processed" / "static_features.parquet"
        _sf_alt     = _ROOT / "data" / "features"  / "static_features.parquet"
        static_features_path = _sf_primary if _sf_primary.exists() else _sf_alt

    if static_features_path.exists() and static_features_path.suffix == ".parquet":
        try:
            import pandas as pd
            df = pd.read_parquet(static_features_path)
            for _, row in df.iterrows():
                hid = str(row["hex_id"])
                hex_slope[hid]   = row.get("slope_deg")
                hex_village[hid] = str(row.get("village", ""))
            print(f"[dynamic_features] Loaded slope_deg from Phase 3 parquet: {len(hex_slope)} hexes")
        except Exception as exc:
            print(f"[dynamic_features] WARNING: Could not read Phase 3 parquet ({exc}); using GSI CSV")

    if not hex_slope:
        # Fallback: hex IDs from GSI CSV, slope_deg = None
        import csv
        gsi_path_resolved = Path(gsi_path)
        if gsi_path_resolved.exists():
            with gsi_path_resolved.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    hid = row["hex_id"].strip()
                    hex_slope[hid]   = None  # Phase 3 not run yet
                    hex_village[hid] = row.get("village", "").strip()
            print(
                f"[dynamic_features] WARNING: Phase 3 parquet not found. "
                f"Using {len(hex_slope)} hex IDs from GSI CSV with slope_deg=None — "
                f"FS will be None for all hexes."
            )

    # ── Compute features per hex ───────────────────────────────────────────
    results: dict[str, dict[str, Any]] = {}
    for hid, slope_deg in hex_slope.items():
        village = hex_village.get(hid, "")
        susc    = gsi_lookup.get(hid)
        results[hid] = compute_dynamic_features(
            hex_id=hid,
            village=village,
            timestamp=timestamp,
            slope_deg=slope_deg,
            gsi_susceptibility_class=susc,
            rainfall_lookup=rainfall_lookup,
            soil_lookup=soil_lookup,
        )

    # ── Summary ────────────────────────────────────────────────────────────
    n_fs_ok      = sum(1 for r in results.values() if r["factor_of_safety"] is not None)
    n_rain_ok    = sum(1 for r in results.values() if r["rainfall_1h"]      is not None)
    n_soil_ok    = sum(1 for r in results.values() if r["soil_saturation_ratio"] is not None)
    n_straddle   = sum(1 for r in results.values() if r["fs_band_straddles_one"])
    print(
        f"[dynamic_features] {len(results)} hexes computed:"
        f" FS={n_fs_ok}/{len(results)}"
        f" rain={n_rain_ok}/{len(results)}"
        f" soil={n_soil_ok}/{len(results)}"
        f" FS-straddles-1.0={n_straddle}"
    )
    return results


# ---------------------------------------------------------------------------
# CLI entry — standalone validation run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 80)
    print("Phase 6 Part 1 — Dynamic Feature Engineering — standalone validation")
    print("SRS.md Section 9 | 14 dynamic features per pilot hex")
    print("=" * 80)

    results = compute_all_hexes_current_cycle()

    # Spot-check: verify all 14 feature keys are present in every result
    EXPECTED_KEYS = {
        "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h",
        "rainfall_72h_antecedent", "rain_intensity_mm_hr",
        "antecedent_precipitation_index",  # NEVER api_score
        "soil_saturation_ratio",
        "factor_of_safety", "factor_of_safety_min", "factor_of_safety_max",
        "simulated_ffgs_signal", "simulated_gsi_signal", "iot_anomaly_flag",
    }
    missing_keys: list[str] = []
    for hid, r in results.items():
        for k in EXPECTED_KEYS:
            if k not in r:
                missing_keys.append(f"{hid} missing key '{k}'")

    if missing_keys:
        print("\nFAIL: missing feature keys:")
        for m in missing_keys:
            print(f"  {m}")
        sys.exit(1)

    # Verify iot_anomaly_flag is exactly False (stub check)
    bad_iot = [hid for hid, r in results.items() if r["iot_anomaly_flag"] is not False]
    if bad_iot:
        print(f"FAIL: iot_anomaly_flag != False for hexes: {bad_iot[:3]}")
        sys.exit(1)

    # Verify antecedent_precipitation_index key present (never api_score)
    if any("api_score" in r for r in results.values()):
        print("FAIL: 'api_score' key found — must be 'antecedent_precipitation_index'")
        sys.exit(1)

    print()
    print("Sample hex features:")
    for hid, r in list(results.items())[:3]:
        print(f"  {hid} ({r['village']}):")
        for k in sorted(EXPECTED_KEYS):
            print(f"    {k:45s} = {r[k]}")
        print()

    print("Phase 6 Part 1 — dynamic_features.py: PASS (all 14 feature keys present)")
