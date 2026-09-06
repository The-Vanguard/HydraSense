"""
backend/lead_time.py -- Phase 9: Lead-time computation + live/demo fallback.

Implements:
  SRS.md Section 12 -- Algorithmic Time-to-Red (hourly, no sub-hour interpolation)
  SRS.md Section 13 -- Live/Demo Data-Source Fallback (3-5s timeout, cached_demo)

Owner: Guhan-10 (Phase 9)

METHOD (SRS ss12, frozen):
  For each hex currently below Red:
  1. Pull Open-Meteo hourly forecast series.
  2. At each hourly step t+1h to t+24h, recompute rainfall features, rerun FusionModel.
  3. lead_time_min = first step (minutes) where projected tier = Red.
     If none crosses: lead_time_min=None, lead_time_basis=no_red_crossing_in_forecast_window.
  Never sub-hour interpolation. Never fabricated numbers.

FALLBACK (SRS ss13, frozen):
  4-second timeout on live Open-Meteo call. On timeout/error -> cached_demo_snapshot.json.
  data_source = "live" or "cached_demo" accordingly.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_VILLAGE_COORDS: dict[str, tuple[float, float]] = {
    "Mundakkai":     (11.5185, 76.0524),
    "Chooralmala":   (11.5143, 76.0498),
    "Attamala":      (11.5220, 76.0570),
    "Punjirimattom": (11.5100, 76.0450),
}
_DEFAULT_LAT, _DEFAULT_LON = 11.5162, 76.0511
_FORECAST_BASE      = "https://api.open-meteo.com/v1/forecast"
_LIVE_TIMEOUT_S     = 4.0            # SRS ss13: 3-5s; 4s chosen
_FORECAST_HORIZON_H = 24             # SRS ss12: up to 24h
_CACHE_PATH         = ROOT / "data" / "weather" / "cached_demo_snapshot.json"
_FORECAST_FILE      = ROOT / "data" / "weather" / "rainfall_forecast.json"


def _fetch_live_forecast(lat: float, lon: float) -> tuple[dict, str]:
    """
    Fetch hourly precipitation forecast. Returns (series_dict, data_source).
    Never raises -- falls through to cached on any error.
    """
    try:
        resp = httpx.get(
            _FORECAST_BASE,
            params={
                "latitude":     lat,
                "longitude":    lon,
                "hourly":       "precipitation",
                "timezone":     "UTC",
                "timeformat":   "iso8601",
                "forecast_days": 2,
            },
            timeout=_LIVE_TIMEOUT_S,
        )
        resp.raise_for_status()
        data   = resp.json()
        times  = data.get("hourly", {}).get("time", [])
        precip = data.get("hourly", {}).get("precipitation", [])
        if times and precip:
            return {"time": times, "precipitation": precip}, "live"
    except Exception:
        pass
    return _load_cached_forecast(lat, lon), "cached_demo"


def _load_cached_forecast(lat: float, lon: float) -> dict:
    """Load cached_demo_snapshot.json or rainfall_forecast.json fallback."""
    for cache_file in [_CACHE_PATH, _FORECAST_FILE]:
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
            times  = series.get("time", [])
            precip = series.get("precipitation_mm", series.get("precipitation", []))
            if times and precip:
                return {"time": times, "precipitation": precip}
        except Exception:
            continue
    return {"time": [], "precipitation": []}


def _extract_forecast_rainfall(
    series: dict,
    ref_time: datetime,
    horizon_h: int,
) -> dict[str, float | None]:
    """
    Extract rolling rainfall windows at (ref_time + horizon_h hours) from forecast.
    Returns the same rainfall keys as compute_dynamic_features expects.
    SRS ss12: uses forecast rainfall only -- no observed data mixed in.
    """
    times  = series.get("time", [])
    precip = series.get("precipitation", [])

    NULL_FEATURES: dict[str, None] = {k: None for k in [
        "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h",
        "rainfall_72h_antecedent", "rain_intensity_mm_hr",
        "antecedent_precipitation_index",
    ]}
    if not times or not precip:
        return NULL_FEATURES

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
            if -72 <= offset_h <= horizon_h + 1:
                hour_map[offset_h] = float(p) if p is not None else 0.0
        except Exception:
            continue

    def window_sum(end_h: int, n_h: int) -> float | None:
        vals = [hour_map.get(h) for h in range(end_h - n_h + 1, end_h + 1)]
        non_null = [v for v in vals if v is not None]
        return sum(non_null) if non_null else None

    r1h  = window_sum(horizon_h, 1)
    r3h  = window_sum(horizon_h, 3)
    r6h  = window_sum(horizon_h, 6)
    r24h = window_sum(horizon_h, 24)

    antecedent_vals = [hour_map.get(h) for h in range(-72, 0)]
    r72h = sum(v for v in antecedent_vals if v is not None) or None
    api  = round(r72h * 0.85 / 3, 4) if r72h is not None else None
    intensity = r1h if r1h is not None else None

    def _r(v: float | None, digits: int = 2) -> float | None:
        return round(v, digits) if v is not None else None

    return {
        "rainfall_1h":                    _r(r1h),
        "rainfall_3h":                    _r(r3h),
        "rainfall_6h":                    _r(r6h),
        "rainfall_24h":                   _r(r24h),
        "rainfall_72h_antecedent":        _r(r72h),
        "rain_intensity_mm_hr":           _r(intensity, 4),
        "antecedent_precipitation_index": api,
    }


def compute_lead_time(
    hex_id: str,
    current_features: dict[str, Any],
) -> tuple[int | None, str, str]:
    """
    Compute forecast-based lead time to Red crossing (SRS ss12). Hourly steps only.

    Args:
        hex_id:           H3 hex identifier (used for lat/lon via h3.cell_to_latlng)
        current_features: current merged static + dynamic features

    Returns:
        (lead_time_min, lead_time_basis, data_source)
        - lead_time_min:  minutes to first Red crossing, or None
        - lead_time_basis: "forecast_hourly_crossing" or
                           "no_red_crossing_in_forecast_window"
        - data_source:    "live" or "cached_demo"

    FROZEN constraints (SRS ss12):
      Hourly steps only. No sub-hour interpolation. null + honest basis = valid output.
    """
    try:
        import h3
        lat, lon = h3.cell_to_latlng(hex_id)
    except Exception:
        lat, lon = _DEFAULT_LAT, _DEFAULT_LON

    ref_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    series, data_source = _fetch_live_forecast(lat, lon)

    # Load fusion model
    try:
        import importlib
        if "ml.models.train_fusion_model" not in sys.modules:
            importlib.import_module("ml.models.train_fusion_model")
        from ml.models.train_fusion_model import FusionModel
        model = FusionModel.load(ROOT / "ml" / "models" / "fusion_model.pkl")
    except Exception as exc:
        return None, f"model_load_error: {exc}", data_source

    # Walk hourly forecast steps t+1h to t+24h (SRS ss12: hourly only)
    for horizon_h in range(1, _FORECAST_HORIZON_H + 1):
        forecast_rain = _extract_forecast_rainfall(series, ref_time, horizon_h)
        features_at_h = dict(current_features)
        features_at_h.update({k: v for k, v in forecast_rain.items() if v is not None})
        try:
            pred = model.predict_one(features_at_h)
        except Exception:
            continue
        if pred.get("tier") == "Red":
            lead_time_min = horizon_h * 60  # hours -> minutes (SRS ss12)
            return lead_time_min, "forecast_hourly_crossing", data_source

    return None, "no_red_crossing_in_forecast_window", data_source



def prefetch_demo_snapshot() -> None:
    """
    Pre-fetch and save demo snapshot for all pilot locations (SRS ss13).
    Run: python data/scripts/cache_demo_snapshot.py before demo day.
    """
    import time as _time
    locations_out = []
    for name, (lat, lon) in _VILLAGE_COORDS.items():
        print(f"  Fetching {name} ({lat}, {lon}) ...", end=" ", flush=True)
        series, src = _fetch_live_forecast(lat, lon)
        times  = series.get("time", [])
        precip = series.get("precipitation", [])
        print(f"{len(times)} hours, source={src}")
        locations_out.append({
            "location": name, "lat": lat, "lon": lon,
            "series": {"time": times, "precipitation_mm": precip},
        })
        _time.sleep(0.5)

    output = {
        "fetched_at":  datetime.now(timezone.utc).isoformat(),
        "data_source": "open_meteo_live_prefetch",
        "note":        "Pre-fetched demo snapshot (SRS ss13). Refresh before going on stage.",
        "locations":   locations_out,
    }
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"  Saved -> {_CACHE_PATH}")
