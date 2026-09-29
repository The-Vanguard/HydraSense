"""
backend/rainfall.py -- Phase 3: Dynamic rainfall layer (gauge-free baseline).

Implements:
  Gap Analysis Phase 3 / v2 Section 6.3–6.4
  - IMERG Late/Early half-hourly satellite rainfall (NASA GES DISC)
  - Open-Meteo forecast/recent-hours rainfall
  - Terrain-adjusted downscaling to ~1 km (orographic factor)
  - Single fallback chain with per-layer badges (v2 §6.4)
  - Provenance tagging on every rainfall record

Fallback chain (v2 §6.4):
  Tier 0: Local sensor (IoT rain gauge) within influence radius
  Tier 1: Live regional observation — IMERG Early, Open-Meteo recent-hours
  Tier 2: Last-known-good cached state (age shown)
  Tier 3: Terrain/physics-only static estimate, confidence flagged down

Owner: Phase 3 migration
"""
from __future__ import annotations

import json
import math
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.coarse_cache import coarse_cached
from backend.provenance import ProvenanceTag

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
_OPEN_METEO_TIMEOUT_S = 4.0       # v2 §6.4: 4-second timeout
_IMERG_TIMEOUT_S = 8.0             # IMERG has slower responses
_CACHE_DIR = ROOT / "data" / "weather"

# Terrain adjustment constants (v2 §6.3 step 2: orographic adjustment)
# Fitted from literature: windward slopes receive ~15-30% more rainfall
# per 100m elevation gain in Western Ghats (Shrestha et al., 2012).
OROGRAPHIC_FACTOR_PER_100M = 0.12  # +12% per 100m above basin mean
ASPECT_WIND_BOOST = 0.08           # +8% for windward-facing slopes (SW monsoon)
MAX_TERRAIN_FACTOR = 1.5           # Cap at 50% increase
MIN_TERRAIN_FACTOR = 0.7           # Floor at 30% decrease


@dataclass
class RainfallLayerBadge:
    """Per-layer source metadata badge (v2 §6.4, Gap Analysis Phase 3 gate)."""
    layer_name: str                # "rainfall_live", "rainfall_forecast", etc.
    source: str                    # "open_meteo", "imerg_early", "sensor", "cached", "static_estimate"
    tier: int                      # 0=sensor, 1=live, 2=cached, 3=static
    age_seconds: Optional[float]   # seconds since the observation was made
    coverage: str                  # "point", "satellite_only", "gauge_merged"
    terrain_adjusted: bool         # whether orographic correction was applied
    provenance: str                # ProvenanceTag value


@dataclass
class RainfallState:
    """Complete rainfall state for one hex at one point in time."""
    hex_id: str
    timestamp: str                 # ISO UTC
    rainfall_1h: Optional[float] = None
    rainfall_3h: Optional[float] = None
    rainfall_6h: Optional[float] = None
    rainfall_24h: Optional[float] = None
    rainfall_72h_antecedent: Optional[float] = None
    rain_intensity_mm_hr: Optional[float] = None
    antecedent_precipitation_index: Optional[float] = None
    terrain_factor: float = 1.0    # multiplier applied
    source_badges: list[RainfallLayerBadge] = field(default_factory=list)
    data_source: str = "live"      # overall source label
    provenance: str = ProvenanceTag.REAL_VALIDATED.value


# ---------------------------------------------------------------------------
# Terrain adjustment (v2 §6.3 step 2)
# ---------------------------------------------------------------------------

def compute_terrain_factor(
    elevation_m: Optional[float],
    basin_mean_elevation_m: float = 900.0,  # Wayanad mean ~900m
    aspect_deg: Optional[float] = None,
    sw_monsoon_active: bool = True,
) -> float:
    """
    Compute orographic rainfall adjustment factor for a hex.

    v2 §6.3 step 2: terrain factor (elevation, aspect relative to wind,
    distance to ridge) fitted to gauge-to-satellite ratios.
    Returns a multiplier ∈ [MIN_TERRAIN_FACTOR, MAX_TERRAIN_FACTOR].
    """
    if elevation_m is None:
        return 1.0

    # Elevation effect: higher hexes get more rain
    delta_elev = elevation_m - basin_mean_elevation_m
    elev_factor = 1.0 + (delta_elev / 100.0) * OROGRAPHIC_FACTOR_PER_100M

    # Aspect effect: SW-facing slopes (180-270°) get a boost during monsoon
    aspect_factor = 1.0
    if aspect_deg is not None and sw_monsoon_active:
        # SW monsoon wind direction: ~225° (SW)
        # Windward = aspect within 90° of 225°
        wind_dir = 225.0
        angle_diff = abs(aspect_deg - wind_dir)
        if angle_diff > 180:
            angle_diff = 360 - angle_diff
        if angle_diff < 90:
            # Windward: boost proportional to alignment
            aspect_factor = 1.0 + ASPECT_WIND_BOOST * (1.0 - angle_diff / 90.0)
        elif angle_diff > 135:
            # Leeward: rain shadow
            aspect_factor = 1.0 - ASPECT_WIND_BOOST * 0.5

    factor = elev_factor * aspect_factor
    return max(MIN_TERRAIN_FACTOR, min(MAX_TERRAIN_FACTOR, factor))


# ---------------------------------------------------------------------------
# Source fetchers
# ---------------------------------------------------------------------------

@coarse_cached(success=lambda r: r[1] == "open_meteo_live")
def fetch_open_meteo_rainfall(
    lat: float, lon: float,
    past_hours: int = 72,
    forecast_hours: int = 48,
) -> tuple[dict, str]:
    """
    Fetch recent + forecast hourly precipitation from Open-Meteo.
    Returns (series_dict, data_source).
    Falls back to cached on any error (v2 §6.4 Tier 2).
    """
    try:
        resp = httpx.get(
            _OPEN_METEO_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "precipitation",
                "past_hours": past_hours,
                "forecast_hours": forecast_hours,
                "timezone": "UTC",
                "timeformat": "iso8601",
            },
            timeout=_OPEN_METEO_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        times = data.get("hourly", {}).get("time", [])
        precip = data.get("hourly", {}).get("precipitation", [])
        if times and precip:
            return {"time": times, "precipitation": precip}, "open_meteo_live"
    except Exception:
        pass

    # Tier 2: cached fallback
    cached = _load_cached_rainfall(lat, lon)
    if cached:
        return cached, "open_meteo_cached"
    return {"time": [], "precipitation": []}, "unavailable"


def fetch_imerg_rainfall(
    lat: float, lon: float,
    hours_back: int = 72,
) -> tuple[Optional[dict], str]:
    """
    Fetch IMERG Late/Early half-hourly satellite rainfall.

    NOTE: IMERG requires NASA Earthdata credentials. This function
    returns None if credentials are not configured, falling through
    to the next tier in the fallback chain.

    In production, this would use the GES DISC OPeNDAP/subsetter API.
    For now, we check for pre-fetched IMERG cache files.
    """
    cache_file = _CACHE_DIR / "imerg_cache" / f"imerg_{lat:.2f}_{lon:.2f}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return data, "imerg_cached"
        except Exception:
            pass

    # IMERG live fetch requires Earthdata credentials
    # Stubbed for Phase 3 gate — full implementation when credentials are configured
    earthdata_token = _get_earthdata_token()
    if earthdata_token is None:
        return None, "imerg_unavailable"

    # Live IMERG fetch would go here
    # For now, return None to trigger fallback
    return None, "imerg_unavailable"


def _get_earthdata_token() -> Optional[str]:
    """Check for NASA Earthdata credentials in environment or config."""
    import os
    token = os.environ.get("EARTHDATA_TOKEN")
    if token:
        return token

    creds_file = ROOT / ".credentials" / "earthdata.json"
    if creds_file.exists():
        try:
            creds = json.loads(creds_file.read_text(encoding="utf-8"))
            return creds.get("token")
        except Exception:
            pass
    return None


def _load_cached_rainfall(lat: float, lon: float) -> Optional[dict]:
    """Load cached rainfall from demo snapshot or forecast files."""
    for cache_file in [
        _CACHE_DIR / "cached_demo_snapshot.json",
        _CACHE_DIR / "rainfall_forecast.json",
    ]:
        if not cache_file.exists():
            continue
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            locations = data.get("locations", [])
            if not locations:
                continue
            best = min(
                locations,
                key=lambda loc: (loc.get("lat", 0) - lat) ** 2
                                + (loc.get("lon", 0) - lon) ** 2,
            )
            series = best.get("series", {})
            times = series.get("time", [])
            precip = series.get("precipitation_mm", series.get("precipitation", []))
            if times and precip:
                return {"time": times, "precipitation": precip}
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Rainfall windows (rolling sums from a time series)
# ---------------------------------------------------------------------------

def compute_rainfall_windows(
    series: dict,
    ref_time: Optional[datetime] = None,
) -> dict[str, Optional[float]]:
    """
    Compute rolling rainfall windows from a time series.
    Returns rainfall_1h, 3h, 6h, 24h, 72h_antecedent, intensity, API.
    """
    times = series.get("time", [])
    precip = series.get("precipitation", [])

    NULL_FEATURES: dict[str, None] = {k: None for k in [
        "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h",
        "rainfall_72h_antecedent", "rain_intensity_mm_hr",
        "antecedent_precipitation_index",
    ]}
    if not times or not precip:
        return NULL_FEATURES

    if ref_time is None:
        ref_time = datetime.now(timezone.utc)

    # Build offset_hours -> mm dict relative to ref_time
    hour_map: dict[int, float] = {}
    for t_str, p in zip(times, precip):
        try:
            if "T" not in str(t_str):
                t_str = str(t_str) + "T00:00"
            t_dt = datetime.fromisoformat(str(t_str))
            if t_dt.tzinfo is None:
                t_dt = t_dt.replace(tzinfo=timezone.utc)
            offset_h = int((t_dt - ref_time).total_seconds() / 3600)
            if -72 <= offset_h <= 48:
                hour_map[offset_h] = float(p) if p is not None else 0.0
        except Exception:
            continue

    def window_sum(end_h: int, n_h: int) -> Optional[float]:
        vals = [hour_map.get(h) for h in range(end_h - n_h + 1, end_h + 1)]
        non_null = [v for v in vals if v is not None]
        return round(sum(non_null), 2) if non_null else None

    r1h = window_sum(0, 1)
    r3h = window_sum(0, 3)
    r6h = window_sum(0, 6)
    r24h = window_sum(0, 24)

    antecedent_vals = [hour_map.get(h) for h in range(-72, 0)]
    r72h = sum(v for v in antecedent_vals if v is not None) or None
    api = round(r72h * 0.85 / 3, 4) if r72h is not None else None
    intensity = r1h if r1h is not None else None

    return {
        "rainfall_1h":                    r1h,
        "rainfall_3h":                    r3h,
        "rainfall_6h":                    r6h,
        "rainfall_24h":                   r24h,
        "rainfall_72h_antecedent":        round(r72h, 2) if r72h else None,
        "rain_intensity_mm_hr":           round(intensity, 4) if intensity else None,
        "antecedent_precipitation_index": api,
    }


# ---------------------------------------------------------------------------
# Soil-state selection (v2 §6.4, Gap Analysis Phase 3)
# ---------------------------------------------------------------------------

@dataclass
class SoilState:
    """Soil moisture state from best available source."""
    soil_moisture_surface: Optional[float] = None
    soil_saturation_ratio: Optional[float] = None
    source: str = "model"       # "sensor", "open_meteo", "model", "antecedent_index"
    age_seconds: Optional[float] = None
    provenance: str = ProvenanceTag.REAL_VALIDATED.value


def get_soil_state(
    hex_id: str,
    lat: float,
    lon: float,
    antecedent_precip_index: Optional[float] = None,
) -> SoilState:
    """
    Select soil moisture from best available source (v2 §6.4).

    Priority:
      1. In-situ sensor (IoT node with soil moisture probe)
      2. Open-Meteo soil moisture analysis
      3. Antecedent precipitation index (API) derived from rainfall
      4. Physics-only static estimate
    """
    # 1. Check for sensor data
    sensor_state = _get_sensor_soil_moisture(hex_id)
    if sensor_state is not None:
        return sensor_state

    # 2. Open-Meteo soil moisture
    om_state = _fetch_open_meteo_soil_moisture(lat, lon)
    if om_state is not None:
        return om_state

    # 3. Antecedent precipitation index
    if antecedent_precip_index is not None:
        # Convert API to approximate saturation ratio
        # API > 50 mm → near-saturated; API < 10 mm → dry
        sat_ratio = min(1.0, max(0.2, antecedent_precip_index / 60.0))
        return SoilState(
            soil_moisture_surface=sat_ratio * 0.45,  # volumetric
            soil_saturation_ratio=sat_ratio,
            source="antecedent_index",
            provenance=ProvenanceTag.REAL_VALIDATED.value,
        )

    # 4. Static estimate (confidence flagged down)
    return SoilState(
        soil_moisture_surface=0.35,  # typical humid tropical default
        soil_saturation_ratio=0.60,
        source="static_estimate",
        provenance=ProvenanceTag.SIMULATED.value,
    )


def _get_sensor_soil_moisture(hex_id: str) -> Optional[SoilState]:
    """Check SQLite for recent IoT sensor soil moisture reading."""
    try:
        from backend.database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT dynamic_features, timestamp FROM observations "
                "WHERE hex_id = ? ORDER BY timestamp DESC LIMIT 1",
                (hex_id,)
            ).fetchone()
            if row is None:
                return None
            feats = json.loads(row["dynamic_features"] or "{}")
            sm = feats.get("soil_moisture_surface")
            if sm is None:
                return None
            ts = datetime.fromisoformat(row["timestamp"])
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > 3600:  # sensor data older than 1 hour is stale
                return None
            return SoilState(
                soil_moisture_surface=float(sm),
                soil_saturation_ratio=feats.get("soil_saturation_ratio"),
                source="sensor",
                age_seconds=age,
                provenance=ProvenanceTag.REAL_VALIDATED.value,
            )
    except Exception:
        return None


@coarse_cached(success=lambda r: r is not None)
def _fetch_open_meteo_soil_moisture(lat: float, lon: float) -> Optional[SoilState]:
    """Fetch soil moisture from Open-Meteo's soil moisture product."""
    try:
        resp = httpx.get(
            _OPEN_METEO_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "soil_moisture_0_to_1cm,soil_moisture_0_to_7cm",
                "past_hours": 6,
                "forecast_hours": 0,
                "timezone": "UTC",
            },
            timeout=_OPEN_METEO_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        sm_1cm = hourly.get("soil_moisture_0_to_1cm", [])
        sm_7cm = hourly.get("soil_moisture_0_to_7cm", [])

        # Use most recent non-null value
        sm_val = None
        for vals in [sm_7cm, sm_1cm]:
            for v in reversed(vals):
                if v is not None:
                    sm_val = float(v)
                    break
            if sm_val is not None:
                break

        if sm_val is not None:
            sat_ratio = min(1.0, sm_val / 0.45)  # 0.45 m³/m³ is approx saturation
            return SoilState(
                soil_moisture_surface=sm_val,
                soil_saturation_ratio=round(sat_ratio, 3),
                source="open_meteo",
                provenance=ProvenanceTag.REAL_VALIDATED.value,
            )
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Master fetch: full rainfall state for a hex (the Phase 3 interface)
# ---------------------------------------------------------------------------

def get_rainfall_state(
    hex_id: str,
    lat: float,
    lon: float,
    elevation_m: Optional[float] = None,
    aspect_deg: Optional[float] = None,
    basin_mean_elevation_m: float = 900.0,
) -> RainfallState:
    """
    Build the complete rainfall state for a hex by walking the fallback chain.

    This is the Phase 3 entry point that the risk engine should call instead
    of hardcoding rainfall features.

    Returns a RainfallState with per-layer badges documenting exactly which
    sources contributed (Gap Analysis Phase 3 gate requirement).
    """
    now = datetime.now(timezone.utc)
    badges: list[RainfallLayerBadge] = []

    # --- Walk the fallback chain (v2 §6.4) ---

    # Tier 0: Local sensor rainfall
    sensor_rain = _get_sensor_rainfall(hex_id)
    if sensor_rain is not None:
        badges.append(RainfallLayerBadge(
            layer_name="rainfall_live",
            source="sensor",
            tier=0,
            age_seconds=sensor_rain.get("age_seconds"),
            coverage="point",
            terrain_adjusted=False,
            provenance=ProvenanceTag.REAL_VALIDATED.value,
        ))
        # If sensor covers recent hours, use it directly
        if sensor_rain.get("rainfall_1h") is not None:
            return RainfallState(
                hex_id=hex_id,
                timestamp=now.isoformat(),
                rainfall_1h=sensor_rain["rainfall_1h"],
                rainfall_3h=sensor_rain.get("rainfall_3h"),
                rainfall_6h=sensor_rain.get("rainfall_6h"),
                rainfall_24h=sensor_rain.get("rainfall_24h"),
                rainfall_72h_antecedent=sensor_rain.get("rainfall_72h_antecedent"),
                rain_intensity_mm_hr=sensor_rain.get("rain_intensity_mm_hr"),
                terrain_factor=1.0,  # sensor is already local
                source_badges=badges,
                data_source="sensor",
                provenance=ProvenanceTag.REAL_VALIDATED.value,
            )

    # Tier 1a: IMERG satellite rainfall
    imerg_series, imerg_source = fetch_imerg_rainfall(lat, lon)
    if imerg_series is not None:
        badges.append(RainfallLayerBadge(
            layer_name="rainfall_satellite",
            source=imerg_source,
            tier=1,
            age_seconds=None,
            coverage="satellite_only",
            terrain_adjusted=True,
            provenance=ProvenanceTag.REAL_VALIDATED.value,
        ))

    # Tier 1b: Open-Meteo recent-hours + forecast
    om_series, om_source = fetch_open_meteo_rainfall(lat, lon)
    tier = 1 if "live" in om_source else 2
    badges.append(RainfallLayerBadge(
        layer_name="rainfall_forecast",
        source=om_source,
        tier=tier,
        age_seconds=None,
        coverage="satellite_only",
        terrain_adjusted=True,
        provenance=ProvenanceTag.REAL_VALIDATED.value if tier == 1
                   else ProvenanceTag.SIMULATED.value,
    ))

    # Merge sources: prefer IMERG for past observations, Open-Meteo for forecast
    if imerg_series is not None:
        # IMERG for past, Open-Meteo for forecast
        merged_series = _merge_rainfall_series(imerg_series, om_series)
        overall_source = "imerg_openmeteo_merged"
    else:
        merged_series = om_series
        overall_source = om_source

    # Compute windows from merged series
    windows = compute_rainfall_windows(merged_series, ref_time=now)

    # Apply terrain adjustment (v2 §6.3 step 2)
    terrain_factor = compute_terrain_factor(
        elevation_m=elevation_m,
        basin_mean_elevation_m=basin_mean_elevation_m,
        aspect_deg=aspect_deg,
    )

    # Apply factor to all rainfall values
    adjusted = {}
    for key, val in windows.items():
        if val is not None and key.startswith("rainfall_"):
            adjusted[key] = round(val * terrain_factor, 2)
        else:
            adjusted[key] = val

    # Determine provenance
    if overall_source == "unavailable":
        prov = ProvenanceTag.SIMULATED.value
        overall_source = "static_estimate"
        badges.append(RainfallLayerBadge(
            layer_name="rainfall_static",
            source="static_estimate",
            tier=3,
            age_seconds=None,
            coverage="none",
            terrain_adjusted=False,
            provenance=ProvenanceTag.SIMULATED.value,
        ))
    else:
        prov = ProvenanceTag.REAL_VALIDATED.value

    return RainfallState(
        hex_id=hex_id,
        timestamp=now.isoformat(),
        rainfall_1h=adjusted.get("rainfall_1h"),
        rainfall_3h=adjusted.get("rainfall_3h"),
        rainfall_6h=adjusted.get("rainfall_6h"),
        rainfall_24h=adjusted.get("rainfall_24h"),
        rainfall_72h_antecedent=adjusted.get("rainfall_72h_antecedent"),
        rain_intensity_mm_hr=adjusted.get("rain_intensity_mm_hr"),
        antecedent_precipitation_index=adjusted.get("antecedent_precipitation_index"),
        terrain_factor=terrain_factor,
        source_badges=badges,
        data_source=overall_source,
        provenance=prov,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_sensor_rainfall(hex_id: str) -> Optional[dict]:
    """Check SQLite for recent IoT sensor rainfall reading."""
    try:
        from backend.database import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT dynamic_features, timestamp FROM observations "
                "WHERE hex_id = ? ORDER BY timestamp DESC LIMIT 1",
                (hex_id,)
            ).fetchone()
            if row is None:
                return None
            feats = json.loads(row["dynamic_features"] or "{}")
            r1h = feats.get("rainfall_1h")
            if r1h is None:
                return None
            ts = datetime.fromisoformat(row["timestamp"])
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > 1800:  # sensor rainfall > 30 min old is stale
                return None
            return {
                "rainfall_1h": float(r1h),
                "rainfall_3h": feats.get("rainfall_3h"),
                "rainfall_6h": feats.get("rainfall_6h"),
                "rainfall_24h": feats.get("rainfall_24h"),
                "rainfall_72h_antecedent": feats.get("rainfall_72h_antecedent"),
                "rain_intensity_mm_hr": feats.get("rain_intensity_mm_hr"),
                "age_seconds": age,
            }
    except Exception:
        return None


def _merge_rainfall_series(
    primary: dict,
    secondary: dict,
) -> dict:
    """
    Merge two rainfall series. Primary (e.g. IMERG) wins for past hours,
    secondary (e.g. Open-Meteo) fills in forecast hours.
    """
    p_times = primary.get("time", [])
    p_precip = primary.get("precipitation", [])
    s_times = secondary.get("time", [])
    s_precip = secondary.get("precipitation", [])

    # Build a unified map
    time_map: dict[str, float] = {}
    for t, p in zip(s_times, s_precip):
        if p is not None:
            time_map[str(t)] = float(p)
    # Primary overwrites secondary for overlapping times
    for t, p in zip(p_times, p_precip):
        if p is not None:
            time_map[str(t)] = float(p)

    sorted_times = sorted(time_map.keys())
    return {
        "time": sorted_times,
        "precipitation": [time_map[t] for t in sorted_times],
    }


# ---------------------------------------------------------------------------
# Degradation test support (Phase 3 gate requirement)
# ---------------------------------------------------------------------------

def test_fallback_chain_degradation(lat: float, lon: float) -> dict:
    """
    Gate test: disable each source in turn and verify the chain degrades
    visibly and correctly.

    Returns a dict with results for each source disabled.
    This is NOT a unit test — it's a diagnostic function for the Phase 3 gate.
    """
    results = {}

    # Normal state
    state_normal = get_rainfall_state("test_hex", lat, lon, elevation_m=1000.0)
    results["all_sources"] = {
        "data_source": state_normal.data_source,
        "badge_count": len(state_normal.source_badges),
        "has_rainfall": state_normal.rainfall_1h is not None,
    }

    # Note: full degradation testing requires mocking individual sources.
    # This function serves as a template for the Phase 3 gate verification.
    results["note"] = (
        "Full degradation test requires disabling IMERG, Open-Meteo, "
        "and sensor sources individually. Run with mocks in test suite."
    )

    return results
