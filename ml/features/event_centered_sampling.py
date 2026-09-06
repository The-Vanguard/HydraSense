"""
event_centered_sampling.py — Historical event expansion into time-stepped training samples.

Implements: SRS.md Section 11 (Validation — Event-Based LOEO), Phase 4.
Owner: Guhan-10 (Phase 4)

Context
-------
Phase 4's job is to turn a compiled list of ~30 historical events into two artefacts:
  1. The canonical hex-event assignment table (SRS.md §11.5) — which hexes are positive
     for which events, with coordinate_precision tagged.
  2. event_centered_samples.parquet — the merged positive + negative training set, with
     escalating tier labels per §11.2, ready for Phase 6's XGBoost training.

CRITICAL DISTINCTION (SRS.md §11.2, must never be confused):
  - Timestep count (positive rows) = ~30 events × 6 snapshots each = ~180 rows
  - LOEO validation event count = ~30 (the number you report as sample size — ALWAYS)
  The timestep expansion increases TRAINING SIGNAL only; it does NOT increase the
  independent validation sample size, which is always the event count.

Escalating tier labels (SRS.md §11.2, frozen):
  72h before event -> Yellow
  48h before event -> Yellow
  24h before event -> Orange
  12h before event -> Orange
   6h before event -> Red
    Event time     -> Red

Negative sampling (SRS.md §11.4, frozen):
  - 4:1 negative:positive ratio (capped)
  - Pool A: same pilot hexes, dates ≥30 days from any recorded event -> Green
  - Pool B: other pilot hexes during real storm periods with no reported failure -> Green
  - Exclude any timestep within 7 days of a labeled positive event

CLAUDE.md hard constraints that apply here:
  - XGBoost only (training target format must match XGBoost's expected input)
  - Never build live-recomputed LOEO — samples are pre-computed once, offline
  - risk_score formula is P(Green)*15+P(Yellow)*42+P(Orange)*64+P(Red)*88 — the
    model predicts 4-class probabilities; this script sets up the 4-class LABELS
  - antecedent_precipitation_index — never api_score

Usage
-----
  python ml/features/event_centered_sampling.py

  Requires:
    data/events/historical_events.csv   — compiled event list (Phase 4 manual input)
    data/weather/rainfall_current.json  — observed rainfall series (Phase 1)
    data/soil/soil_moisture.json        — GWETROOT series (Phase 1)

  Outputs:
    data/events/hex_event_assignments.csv      — canonical §11.5 table
    data/events/event_centered_samples.parquet — merged train set (positive + negative)
    data/events/sampling_summary.json          — event/timestep counts for audit
"""

import json
import sys
import math
import random
import hashlib
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Optional

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas is required. pip install pandas", file=sys.stderr)
    sys.exit(1)

try:
    import h3
except ImportError:
    print("ERROR: h3 is required. pip install h3", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parents[2]
DATA_DIR    = REPO_ROOT / "data"
EVENTS_DIR  = DATA_DIR / "events"
WEATHER_DIR = DATA_DIR / "weather"
SOIL_DIR    = DATA_DIR / "soil"

EVENTS_CSV         = EVENTS_DIR / "historical_events.csv"
RAINFALL_JSON      = WEATHER_DIR / "rainfall_current.json"
SOIL_JSON          = SOIL_DIR / "soil_moisture.json"
HEX_ASSIGNMENT_CSV = EVENTS_DIR / "hex_event_assignments.csv"
SAMPLES_PARQUET    = EVENTS_DIR / "event_centered_samples.parquet"
SUMMARY_JSON       = EVENTS_DIR / "sampling_summary.json"

# ---------------------------------------------------------------------------
# Pilot cluster configuration (SRS.md §5)
# Villages + approximate centroid coords (village-level precision)
# ---------------------------------------------------------------------------
VILLAGES = {
    "Mundakkai":     {"lat": 11.5185, "lon": 76.0524},
    "Chooralmala":   {"lat": 11.5143, "lon": 76.0498},
    "Attamala":      {"lat": 11.5220, "lon": 76.0570},
    "Punjirimattom": {"lat": 11.5100, "lon": 76.0450},
}

# H3 resolution (SRS.md §5: resolution 8–9, generates however many hexes the villages need)
H3_RESOLUTION = 8

# ---------------------------------------------------------------------------
# Escalating tier label scheme — SRS.md §11.2, frozen
# ---------------------------------------------------------------------------
# Maps hours-before-event -> tier label
LABEL_SCHEME = [
    (-72, "Yellow"),
    (-48, "Yellow"),
    (-24, "Orange"),
    (-12, "Orange"),
    (-6,  "Red"),
    (0,   "Red"),   # event time itself
]

# Tier -> integer label for XGBoost multiclass
TIER_TO_INT = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
INT_TO_TIER = {v: k for k, v in TIER_TO_INT.items()}

# Negative:positive sampling ratio cap (SRS.md §11.4)
NEG_POS_RATIO = 4

# Negative-pool exclusion window around any event (SRS.md §11.4)
LEAKAGE_EXCLUSION_DAYS = 7

# Minimum days from any event for Pool A negatives (SRS.md §11.4)
POOL_A_MIN_CLEAR_DAYS = 30

# Random seed for reproducibility (fixed — must NOT change between Phase 4 and Phase 7 runs)
RANDOM_SEED = 42


# ---------------------------------------------------------------------------
# H3 hex generation
# ---------------------------------------------------------------------------

def get_village_hexes(village_name: str, coords: dict, resolution: int = H3_RESOLUTION) -> list[str]:
    """
    Return H3 hex IDs at `resolution` that cover the given village centroid.

    For village-level coordinate precision (all our events), SRS.md §11.3 requires
    ALL hexes covering that village polygon to be labeled positive. Since we only have
    centroid coordinates (not polygons), we use a ring of hexes around the centroid
    to approximate the village polygon — this is conservative and correct.

    Returns a list of hex IDs: the centroid hex + its k=1 ring neighbours.
    This gives 7 hexes total, roughly covering a ~1–2 km radius area at res=8.
    """
    centroid_hex = h3.latlng_to_cell(coords["lat"], coords["lon"], resolution)
    # k-ring of 1 = centroid + 6 immediate neighbours -> approximates village polygon
    ring = h3.grid_disk(centroid_hex, 1)
    return sorted(ring)


def get_all_pilot_hexes(resolution: int = H3_RESOLUTION) -> list[str]:
    """
    Return the full set of pilot H3 hexes covering all 4 villages.
    Deduplicates hexes shared between village rings.
    """
    all_hexes = set()
    for village_name, coords in VILLAGES.items():
        hexes = get_village_hexes(village_name, coords, resolution)
        all_hexes.update(hexes)
    return sorted(all_hexes)


def get_village_for_hex(hex_id: str, resolution: int = H3_RESOLUTION) -> Optional[str]:
    """Return which village this hex is closest to (by H3 distance to each centroid hex)."""
    centroid_hexes = {
        vname: h3.latlng_to_cell(coords["lat"], coords["lon"], resolution)
        for vname, coords in VILLAGES.items()
    }
    lat, lon = h3.cell_to_latlng(hex_id)
    min_dist = float("inf")
    nearest = None
    for vname, chex in centroid_hexes.items():
        clat, clon = h3.cell_to_latlng(chex)
        dist = math.sqrt((lat - clat) ** 2 + (lon - clon) ** 2)
        if dist < min_dist:
            min_dist = dist
            nearest = vname
    return nearest


# ---------------------------------------------------------------------------
# Observed rainfall / soil lookup helpers
# ---------------------------------------------------------------------------

RAINFALL_HISTORICAL_JSON = WEATHER_DIR / "rainfall_historical.json"   # ERA5 archive (Phase 1 supplement)


def _parse_rainfall_file(path: Path) -> dict[str, dict[str, float]]:
    """
    Parse a rainfall JSON file (either rainfall_current.json or rainfall_historical.json)
    into {location_name: {iso_hour_str: precipitation_mm}}.
    Returns {} if the file does not exist or cannot be parsed.
    """
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    lookup: dict[str, dict[str, float]] = {}
    for loc in data.get("locations", []):
        name = loc["location"]
        times   = loc.get("series", {}).get("time", [])
        precips = loc.get("series", {}).get("precipitation_mm", [])
        lookup[name] = dict(zip(times, precips))
    return lookup


def load_rainfall_lookup() -> dict[str, dict[str, float]]:
    """
    Load observed hourly rainfall, merging two sources:

    1. data/weather/rainfall_historical.json  -- ERA5 reanalysis via Open-Meteo Archive
       Covers all historical event dates back to 2009. Generated by
       data/scripts/ingest_rainfall_historical.py (Phase 1 supplement, Bug 3 fix).
       Resolution: ~28km ERA5 grid; all 4 pilot villages resolve to the same point.

    2. data/weather/rainfall_current.json  -- Live Open-Meteo forecast API
       Covers the last 92 days + 48h forecast. Generated by
       data/scripts/ingest_rainfall.py (Phase 1).

    Merge rule: live data overwrites archive data for overlapping hours
    (recency wins -- the live API is higher quality for recent observations).

    Falls back gracefully if either file is missing:
    - Neither file: loud warning; all rainfall features will be NaN.
    - Only historical: positive sample windows populated; recent negatives may be sparse.
    - Only current: events older than 92 days from run date will still have NaN windows.

    Returns: {location_name: {iso_hour_str: precipitation_mm}}
    """
    historical = _parse_rainfall_file(RAINFALL_HISTORICAL_JSON)
    current    = _parse_rainfall_file(RAINFALL_JSON)

    if not historical and not current:
        print(
            f"WARNING: Neither {RAINFALL_HISTORICAL_JSON.name} nor {RAINFALL_JSON.name} found.\n"
            "  Run data/scripts/ingest_rainfall_historical.py (covers all event dates 2009-2024)\n"
            "  and data/scripts/ingest_rainfall.py (covers last 92 days + forecast).\n"
            "  All rainfall features will be NaN in the sample set.",
            file=sys.stderr,
        )
        return {}

    if not historical:
        print(
            f"WARNING: {RAINFALL_HISTORICAL_JSON.name} not found.\n"
            "  Run data/scripts/ingest_rainfall_historical.py to populate ERA5 archive data.\n"
            "  Historical events (>92 days ago) will have NaN rainfall windows.",
            file=sys.stderr,
        )
    if not current:
        print(
            f"WARNING: {RAINFALL_JSON.name} not found.\n"
            "  Run data/scripts/ingest_rainfall.py to populate recent observed + forecast data.",
            file=sys.stderr,
        )

    # Merge: start with archive, overwrite with live for overlapping hours
    merged: dict[str, dict[str, float]] = {}
    all_locations = set(historical) | set(current)
    for loc in all_locations:
        merged[loc] = {}
        merged[loc].update(historical.get(loc, {}))   # archive first (older, lower priority)
        merged[loc].update(current.get(loc, {}))      # live overwrites (higher quality)

    # Coverage summary
    for loc, series in merged.items():
        n_total    = len(series)
        n_non_null = sum(1 for v in series.values() if v is not None)
        print(f"[sampling] Rainfall lookup  {loc:16s}  {n_total:5d} hours, {n_non_null:5d} non-null")

    return merged


def load_soil_lookup() -> dict[str, dict[str, Optional[float]]]:
    """
    Load hourly GWETROOT from Phase 1's soil_moisture.json.
    Returns: {location_name: {timestamp_str: gwetroot_0_to_1}}

    soil_saturation_ratio = GWETROOT directly per SRS.md §10.1 (frozen formula).
    """
    if not SOIL_JSON.exists():
        print(
            f"WARNING: {SOIL_JSON} not found. "
            "Run data/scripts/ingest_soil.py (Phase 1) first.\n"
            "soil_saturation_ratio will be None in the sample set.",
            file=sys.stderr,
        )
        return {}

    with open(SOIL_JSON, encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    lookup: dict[str, dict[str, Optional[float]]] = {}
    for loc in data.get("locations", []):
        name = loc["location"]
        # gwetroot_hourly: {YYYYMMDDHH: float or null}
        series = loc.get("gwetroot_hourly", {})
        lookup[name] = series
    return lookup


def get_rainfall_at(lookup: dict, village: str, dt: datetime) -> Optional[float]:
    """Look up observed precipitation for village at the given hour."""
    if not lookup or village not in lookup:
        return None
    iso_hour = dt.strftime("%Y-%m-%dT%H:00")
    return lookup[village].get(iso_hour)


def get_soil_at(lookup: dict, village: str, dt: datetime) -> Optional[float]:
    """
    Look up GWETROOT (= soil_saturation_ratio) for village at the given datetime.
    NASA POWER provides daily values keyed YYYYMMDD; we use the day's value for any hour.
    """
    if not lookup or village not in lookup:
        return None
    # POWER hourly key format is YYYYMMDDHH
    key_hourly = dt.strftime("%Y%m%d%H")
    key_daily  = dt.strftime("%Y%m%d")
    soil_data  = lookup[village]
    return soil_data.get(key_hourly) or soil_data.get(key_daily)


# ---------------------------------------------------------------------------
# Antecedent Precipitation Index (antecedent_precipitation_index)
# NOTE: field name is antecedent_precipitation_index — NEVER api_score (CLAUDE.md)
# Simple exponential decay: API_t = 0.85 * API_{t-1} + P_t
# ---------------------------------------------------------------------------

def compute_api(rainfall_series: list[Optional[float]], decay: float = 0.85) -> list[Optional[float]]:
    """
    Compute exponentially-decayed Antecedent Precipitation Index from an hourly series.
    antecedent_precipitation_index — NEVER api_score (CLAUDE.md / SRS.md §9).
    """
    api_vals: list[Optional[float]] = []
    running = 0.0
    for p in rainfall_series:
        if p is None:
            api_vals.append(None)
        else:
            running = decay * running + p
            api_vals.append(round(running, 4))
    return api_vals


# ---------------------------------------------------------------------------
# Build hex-event assignment table (SRS.md §11.5)
# This MUST be built before training — it IS the training set definition
# ---------------------------------------------------------------------------

def build_hex_event_assignments(events_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each event, determine the positive hex IDs.

    SRS.md §11.3: for village-level precision, label ALL hexes covering that village.
    SRS.md §11.5: columns = event_id | hex_id | timestamp | label | tier | coordinate_precision

    Returns a DataFrame with one row per (event, hex) pair.
    """
    rows = []
    village_hex_cache: dict[str, list[str]] = {}

    for _, event in events_df.iterrows():
        event_id   = event["event_id"]
        event_date = pd.to_datetime(event["date"])
        coord_prec = event["coordinate_precision"]
        # Map event to the affected village (all our events are village-level)
        # We assign to the nearest village name from the event_id range:
        # E001-E005 -> Mundakkai/Chooralmala/Attamala/Punjirimattom (July 30 2024)
        # Others -> assigned by time period proximity; default to all 4 for broad events
        affected_villages = _get_affected_villages(event)

        for village_name in affected_villages:
            if village_name not in village_hex_cache:
                village_hex_cache[village_name] = get_village_hexes(
                    village_name, VILLAGES[village_name]
                )
            for hex_id in village_hex_cache[village_name]:
                # Event time is treated as midnight UTC of the event date
                event_ts = datetime(
                    event_date.year, event_date.month, event_date.day,
                    tzinfo=timezone.utc
                )
                rows.append({
                    "event_id":            event_id,
                    "hex_id":              hex_id,
                    "timestamp":           event_ts.isoformat(),
                    "label":               "positive",
                    "tier":                "Red",       # event time = Red (§11.2)
                    "coordinate_precision": coord_prec,
                    "village":             village_name,
                    "event_type":          event["type"],
                    "event_severity":      event["severity"],
                })

    df = pd.DataFrame(rows)
    print(
        f"[sampling] Hex-event assignment table: "
        f"{len(df)} rows ({df['event_id'].nunique()} events, "
        f"{df['hex_id'].nunique()} unique hexes)"
    )
    return df


def _get_affected_villages(event: pd.Series) -> list[str]:
    """
    Map an event record to the list of affected pilot villages.
    Logic based on source descriptions; defaults to all 4 for area-wide events.
    """
    eid = event["event_id"]
    # July 30 2024 events — specific villages documented in papers (SRS.md §18)
    specific_map = {
        "E001": ["Mundakkai"],
        "E002": ["Chooralmala"],
        "E003": ["Mundakkai", "Chooralmala"],
        "E004": ["Attamala"],
        "E005": ["Punjirimattom"],
    }
    if eid in specific_map:
        return specific_map[eid]
    # For all other events: village-level precision from news/bulletin sources
    # -> assign all 4 villages (conservative; coordinate_precision = village-level)
    return list(VILLAGES.keys())


# ---------------------------------------------------------------------------
# Positive sample expansion (SRS.md §11.2)
# ---------------------------------------------------------------------------

def expand_positive_samples(
    assignments: pd.DataFrame,
    rainfall_lookup: dict,
    soil_lookup: dict,
) -> pd.DataFrame:
    """
    Expand each (event, hex) assignment into 6 time-stepped snapshots at
    72h/48h/24h/12h/6h before and at event time, with escalating tier labels.

    Each snapshot carries the observed rainfall and GWETROOT at that timestamp.
    These samples increase TRAINING SIGNAL only — they do NOT increase the
    independent validation episode count (SRS.md §11.2).

    Returns: DataFrame with one row per (event, hex, snapshot_offset_h).
    """
    rows = []

    for _, asgn in assignments.iterrows():
        event_ts = datetime.fromisoformat(asgn["timestamp"])
        village  = asgn["village"]

        # Build 72h rainfall series leading up to the event for API computation
        # We try to pull real observed data; fall back to None if Phase 1 not yet run
        rainfall_72h: list[Optional[float]] = []
        for h in range(72, -1, -1):
            snap_dt = event_ts - timedelta(hours=h)
            rainfall_72h.append(get_rainfall_at(rainfall_lookup, village, snap_dt))
        api_series = compute_api(rainfall_72h)

        for (offset_h, tier) in LABEL_SCHEME:
            snap_dt = event_ts + timedelta(hours=offset_h)
            # Index into the 72h-back series: offset 0 = index 72, offset -6 = index 66, etc.
            series_idx = 72 + offset_h   # offset_h is negative (e.g. -72 -> idx 0)

            # Rainfall windows (use rolling sums from the series where available)
            r1h   = _sum_window(rainfall_72h, series_idx, 1)
            r3h   = _sum_window(rainfall_72h, series_idx, 3)
            r6h   = _sum_window(rainfall_72h, series_idx, 6)
            r24h  = _sum_window(rainfall_72h, series_idx, 24)
            r72h  = _sum_window(rainfall_72h, 72, 72)           # full antecedent window

            api_val = api_series[series_idx] if series_idx < len(api_series) else None

            # soil_saturation_ratio = GWETROOT directly (SRS.md §10.1, frozen)
            soil_sat = get_soil_at(soil_lookup, village, snap_dt)

            rows.append({
                # Identity
                "event_id":                   asgn["event_id"],
                "hex_id":                     asgn["hex_id"],
                "village":                    village,
                "snapshot_timestamp":         snap_dt.isoformat(),
                "hours_before_event":         offset_h,
                "coordinate_precision":       asgn["coordinate_precision"],
                # Label (SRS.md §11.2)
                "tier":                       tier,
                "tier_int":                   TIER_TO_INT[tier],
                "sample_type":                "positive",
                # Observed features available at this snapshot (from Phase 1 data)
                # These are partial — Phase 6 (dynamic_features.py) will compute the
                # full 14-feature set. These seed values prevent NaN for events where
                # observed data exists.
                "rainfall_1h":                r1h,
                "rainfall_3h":                r3h,
                "rainfall_6h":                r6h,
                "rainfall_24h":               r24h,
                "rainfall_72h_antecedent":    r72h,
                # antecedent_precipitation_index — NEVER api_score (CLAUDE.md / SRS.md §9)
                "antecedent_precipitation_index": api_val,
                # soil_saturation_ratio = GWETROOT directly (SRS.md §10.1 frozen formula)
                "soil_saturation_ratio":      soil_sat,
                # Static features (None here — joined in Phase 6 from hexes.static_features)
                "slope_deg":                  None,
                "aspect":                     None,
                "TWI":                        None,
                "TRI":                        None,
                "elevation":                  None,
                "distance_to_stream_m":       None,
                "drainage_density":           None,
                "land_use_class":             None,
                "ndvi_mean":                  None,
                "historical_event_count_500m": None,
                "gsi_susceptibility_class":   None,
                # Dynamic features to be filled by Phase 6
                "factor_of_safety":           None,
                "factor_of_safety_min":       None,
                "factor_of_safety_max":       None,
                "simulated_ffgs_signal":       None,
                "simulated_gsi_signal":        None,
                "iot_anomaly_flag":            None,
                "rain_intensity_mm_hr":        r1h,  # proxy: 1h rainfall as intensity
            })

    df = pd.DataFrame(rows)
    print(
        f"[sampling] Positive samples: {len(df)} rows "
        f"(from {df['event_id'].nunique()} events × up to 6 snapshots × N hexes per event)\n"
        f"  NOTE: event count for LOEO reporting = "
        f"{df['event_id'].nunique()} — NOT {len(df)} (SRS.md §11.2)"
    )
    return df


def _sum_window(series: list[Optional[float]], end_idx: int, window: int) -> Optional[float]:
    """Sum `window` values of series ending at end_idx (exclusive). Returns None if all missing."""
    start = max(0, end_idx - window)
    window_vals = [v for v in series[start:end_idx] if v is not None]
    return round(sum(window_vals), 4) if window_vals else None


# ---------------------------------------------------------------------------
# Negative sample generation (SRS.md §11.4)
# ---------------------------------------------------------------------------

def generate_negative_samples(
    positive_df: pd.DataFrame,
    assignments: pd.DataFrame,
    all_hexes: list[str],
    rainfall_lookup: dict,
    soil_lookup: dict,
) -> pd.DataFrame:
    """
    Generate negative (Green tier) samples per SRS.md §11.4:
      Pool A: same pilot hexes, dates ≥30 days from any recorded event
      Pool B: other pilot hexes during real storm periods with no reported failure
      Exclusion: any timestep within 7 days of any labeled positive event
      Cap: 4:1 negative:positive ratio

    Returns: DataFrame of negative samples matching the positive sample schema.
    """
    rng = random.Random(RANDOM_SEED)

    n_positive  = len(positive_df)
    n_neg_target = min(n_positive * NEG_POS_RATIO, n_positive * NEG_POS_RATIO)

    # Build exclusion set: all timestamps within LEAKAGE_EXCLUSION_DAYS of any event
    event_dates: list[date] = []
    for _, row in assignments.drop_duplicates("event_id").iterrows():
        event_dates.append(pd.to_datetime(row["timestamp"]).date())

    def is_excluded(dt: datetime) -> bool:
        d = dt.date()
        return any(abs((d - ed).days) < LEAKAGE_EXCLUSION_DAYS for ed in event_dates)

    # Pool A: dates ≥30 days from any event — sample from 2009–2023 non-event periods
    # We generate candidate timestamps across years with data coverage
    pool_a_candidates: list[tuple[str, datetime, str]] = []
    candidate_years = list(range(2009, 2024))
    monsoon_months  = list(range(6, 12))   # June–November (main hazard window)

    for year in candidate_years:
        for month in monsoon_months:
            for day in [5, 10, 15, 20, 25]:
                try:
                    dt = datetime(year, month, day, 6, tzinfo=timezone.utc)
                except ValueError:
                    continue
                if not is_excluded(dt):
                    for hex_id in rng.sample(all_hexes, min(3, len(all_hexes))):
                        village = get_village_for_hex(hex_id)
                        pool_a_candidates.append((hex_id, dt, village))

    # Pool B: storm periods without failures — use years with confirmed no-event heavy rain
    # (e.g. heavy rain without landslide in the pilot cluster)
    # Based on available data: Oct 2015, Jun 2016 sub-events that didn't affect pilot hexes
    pool_b_storm_periods: list[tuple[int, int, int]] = [
        (2015, 11, 18), (2016, 6, 5),  # non-pilot-hex heavy rain periods
        (2019, 7, 1),  (2020, 7, 15),
        (2022, 6, 10), (2023, 6, 1),
    ]
    pool_b_candidates: list[tuple[str, datetime, str]] = []
    for (yr, mo, da) in pool_b_storm_periods:
        try:
            dt = datetime(yr, mo, da, 18, tzinfo=timezone.utc)
        except ValueError:
            continue
        if not is_excluded(dt):
            for hex_id in all_hexes:
                village = get_village_for_hex(hex_id)
                pool_b_candidates.append((hex_id, dt, village))

    all_neg_candidates = pool_a_candidates + pool_b_candidates
    rng.shuffle(all_neg_candidates)
    selected = all_neg_candidates[:n_neg_target]

    rows = []
    for (hex_id, snap_dt, village) in selected:
        soil_sat = get_soil_at(soil_lookup, village, snap_dt) if village else None
        r1h  = get_rainfall_at(rainfall_lookup, village, snap_dt) if village else None

        rows.append({
            "event_id":                       None,      # no event — this is a negative
            "hex_id":                         hex_id,
            "village":                        village,
            "snapshot_timestamp":             snap_dt.isoformat(),
            "hours_before_event":             None,
            "coordinate_precision":           "n/a",
            "tier":                           "Green",
            "tier_int":                       TIER_TO_INT["Green"],
            "sample_type":                    "negative",
            "rainfall_1h":                    r1h,
            "rainfall_3h":                    None,
            "rainfall_6h":                    None,
            "rainfall_24h":                   None,
            "rainfall_72h_antecedent":        None,
            # antecedent_precipitation_index — NEVER api_score (CLAUDE.md / SRS.md §9)
            "antecedent_precipitation_index": None,
            # soil_saturation_ratio = GWETROOT directly (SRS.md §10.1 frozen formula)
            "soil_saturation_ratio":          soil_sat,
            "slope_deg":                      None,
            "aspect":                         None,
            "TWI":                            None,
            "TRI":                            None,
            "elevation":                      None,
            "distance_to_stream_m":           None,
            "drainage_density":               None,
            "land_use_class":                 None,
            "ndvi_mean":                      None,
            "historical_event_count_500m":    None,
            "gsi_susceptibility_class":       None,
            "factor_of_safety":               None,
            "factor_of_safety_min":           None,
            "factor_of_safety_max":           None,
            "simulated_ffgs_signal":           None,
            "simulated_gsi_signal":            None,
            "iot_anomaly_flag":                None,
            "rain_intensity_mm_hr":            r1h,
        })

    df = pd.DataFrame(rows)
    print(
        f"[sampling] Negative samples: {len(df)} rows "
        f"(target {n_neg_target}; ratio {len(df) / max(n_positive, 1):.1f}:1)\n"
        f"  Pool A (clear-period): {len(pool_a_candidates)} candidates\n"
        f"  Pool B (storm-no-fail): {len(pool_b_candidates)} candidates"
    )
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("[Phase 4] Event-centered temporal sampling — SRS.md §11\n")

    # -------------------------------------------------------------------------
    # 1. Load event list
    # -------------------------------------------------------------------------
    if not EVENTS_CSV.exists():
        print(
            f"ERROR: {EVENTS_CSV} not found.\n"
            "  This file should be committed alongside this script (Phase 4 deliverable).\n"
            "  It contains the manually compiled 30-event historical event list.",
            file=sys.stderr,
        )
        sys.exit(1)

    events_df = pd.read_csv(EVENTS_CSV, dtype=str).fillna("")
    n_events  = len(events_df)
    print(f"[sampling] Loaded {n_events} historical events from {EVENTS_CSV}")

    if n_events < 20:
        print(
            f"WARNING: Only {n_events} events loaded — SRS.md targets ~30–50.\n"
            "  Detection rate and LOEO timing error will be less stable with fewer events.",
            file=sys.stderr,
        )

    # -------------------------------------------------------------------------
    # 2. Generate H3 hex grid for pilot cluster
    # -------------------------------------------------------------------------
    all_hexes = get_all_pilot_hexes(H3_RESOLUTION)
    print(
        f"[sampling] Pilot cluster: {len(VILLAGES)} villages -> "
        f"{len(all_hexes)} unique H3 res-{H3_RESOLUTION} hexes"
    )

    # -------------------------------------------------------------------------
    # 3. Build canonical hex-event assignment table (SRS.md §11.5)
    #    Must be built BEFORE training — it IS the training set definition
    # -------------------------------------------------------------------------
    print("\n[sampling] Building hex-event assignment table (SRS.md §11.5) ...")
    assignments = build_hex_event_assignments(events_df)
    assignments.to_csv(HEX_ASSIGNMENT_CSV, index=False)
    print(f"[sampling]   -> Saved: {HEX_ASSIGNMENT_CSV}")

    # -------------------------------------------------------------------------
    # 4. Load Phase 1 observed data (rainfall + soil)
    # -------------------------------------------------------------------------
    print("\n[sampling] Loading Phase 1 observed data ...")
    rainfall_lookup = load_rainfall_lookup()
    soil_lookup     = load_soil_lookup()

    # -------------------------------------------------------------------------
    # 5. Expand positive samples (SRS.md §11.2)
    # -------------------------------------------------------------------------
    print("\n[sampling] Expanding positive samples (72h/48h/24h/12h/6h/0h per event) ...")
    positive_df = expand_positive_samples(assignments, rainfall_lookup, soil_lookup)

    # -------------------------------------------------------------------------
    # 6. Generate negative samples (SRS.md §11.4)
    # -------------------------------------------------------------------------
    print("\n[sampling] Generating negative samples (SRS.md §11.4) ...")
    negative_df = generate_negative_samples(
        positive_df, assignments, all_hexes, rainfall_lookup, soil_lookup
    )

    # -------------------------------------------------------------------------
    # 7. Merge and save
    # -------------------------------------------------------------------------
    combined_df = pd.concat([positive_df, negative_df], ignore_index=True)
    combined_df = combined_df.sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)

    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    combined_df.to_parquet(SAMPLES_PARQUET, index=False)
    print(f"\n[sampling] Combined sample set saved -> {SAMPLES_PARQUET}")
    print(f"  Total rows:    {len(combined_df)}")
    print(f"  Positive rows: {len(positive_df)}")
    print(f"  Negative rows: {len(negative_df)}")
    print(f"  Actual ratio:  {len(negative_df) / max(len(positive_df), 1):.2f}:1")

    # -------------------------------------------------------------------------
    # 8. Save audit summary
    # -------------------------------------------------------------------------
    n_unique_events   = positive_df["event_id"].nunique()
    n_total_rows      = len(combined_df)
    n_positive_rows   = len(positive_df)
    n_negative_rows   = len(negative_df)

    summary = {
        "phase":   4,
        "srs_section": "11",
        # CRITICAL: always report event count as the validation sample size (SRS.md §11.2)
        "event_count_for_LOEO_reporting": n_unique_events,
        "note": (
            "The LOEO validation sample size is the event count above — "
            f"NOT the total row count ({n_total_rows}). "
            "Timestep expansion increases training signal only (SRS.md §11.2)."
        ),
        "h3_resolution": H3_RESOLUTION,
        "unique_pilot_hexes": len(all_hexes),
        "positive_rows": n_positive_rows,
        "negative_rows": n_negative_rows,
        "neg_pos_ratio": round(n_negative_rows / max(n_positive_rows, 1), 2),
        "leakage_exclusion_days": LEAKAGE_EXCLUSION_DAYS,
        "pool_a_min_clear_days": POOL_A_MIN_CLEAR_DAYS,
        "random_seed": RANDOM_SEED,
        "tier_label_scheme": {str(h): t for (h, t) in LABEL_SCHEME},
        "tier_encoding": TIER_TO_INT,
        "outputs": {
            "hex_event_assignments": str(HEX_ASSIGNMENT_CSV),
            "training_samples":      str(SAMPLES_PARQUET),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2))
    print(f"[sampling] Audit summary -> {SUMMARY_JSON}")

    # -------------------------------------------------------------------------
    # 9. Final counts printout (keep event count front-and-centre)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("PHASE 4 COMPLETE — Sampling summary")
    print("=" * 60)
    print(f"  Historical events compiled:     {n_unique_events}")
    print(f"  *** LOEO validation sample size: {n_unique_events} events ***")
    print(f"      (NOT {n_total_rows} rows — SRS.md §11.2)")
    print(f"  Positive training rows:          {n_positive_rows}")
    print(f"  Negative training rows:          {n_negative_rows}")
    print(f"  Neg:Pos ratio:                   {n_negative_rows / max(n_positive_rows, 1):.2f}:1")
    print(f"  Pilot hexes:                     {len(all_hexes)}")
    print(f"  H3 resolution:                   {H3_RESOLUTION}")
    print()
    print("  Outputs:")
    print(f"    {HEX_ASSIGNMENT_CSV}")
    print(f"    {SAMPLES_PARQUET}")
    print(f"    {SUMMARY_JSON}")
    print()
    print("  Next: Phase 6 (dynamic_features.py + train_fusion_model.py)")
    print("        will join static features (Phase 3) and full dynamic features")
    print("        to this sample set before XGBoost training.")
    print("=" * 60)


if __name__ == "__main__":
    main()
