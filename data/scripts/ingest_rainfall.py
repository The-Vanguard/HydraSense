"""
ingest_rainfall.py — Pull current + hourly forecast rainfall from Open-Meteo API.

Implements: SRS.md Section 8 (Data Sources), Section 13 (Live/Demo Fallback).
Owner: Dev A (Phase 1)

Open-Meteo is free, requires no API key, and provides hourly observed + forecast rainfall
for any lat/lon. This script pulls both series for the Wayanad pilot cluster bounding box
(Mundakkai, Chooralmala, Attamala, Punjirimattom — SRS.md Section 5).

Output files:
  data/weather/rainfall_current.json   — current observation series
  data/weather/rainfall_forecast.json  — hourly forecast series (required for lead-time
                                         computation in Phase 9, SRS.md Section 12)

HARD CONSTRAINT (CLAUDE.md / SRS.md Section 26):
  - On failure, this script exits with a non-zero code and a clear error message.
  - It does NOT silently substitute fake data.
  - The timeout is 5 seconds per SRS.md Section 13.
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Pilot cluster bounding box — Wayanad, Kerala
# Covers Mundakkai, Chooralmala, Attamala, Punjirimattom (SRS.md Section 5)
# Four representative points: one per named village, used as API query locations.
# The H3 grid is generated in Phase 3; Phase 1 pulls data for the cluster centroid
# and per-village points to cover the area.
# ---------------------------------------------------------------------------
PILOT_LOCATIONS = [
    {"name": "Mundakkai",      "lat": 11.5185, "lon": 76.0524},
    {"name": "Chooralmala",    "lat": 11.5143, "lon": 76.0498},
    {"name": "Attamala",       "lat": 11.5220, "lon": 76.0570},
    {"name": "Punjirimattom",  "lat": 11.5100, "lon": 76.0450},
]

# API settings per SRS.md Section 13 — 5-second timeout, no silent failure
OPEN_METEO_BASE = "https://api.open-meteo.com/v1"
TIMEOUT_SECONDS = 5.0

# Output directories
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "weather"


def fetch_rainfall_for_location(lat: float, lon: float, name: str) -> dict:
    """
    Fetch current + hourly forecast rainfall from Open-Meteo for a single lat/lon.

    Returns a dict with keys 'current' and 'forecast' per the Open-Meteo response shape.
    Raises RuntimeError on network failure or timeout — never substitutes fake data.

    SRS.md Section 13: timeout is 5 seconds. On timeout or error, caller must surface
    the failure loudly so the pipeline knows to use cached_demo_snapshot instead.
    """
    # -------------------------------------------------------------------------
    # Open-Meteo forecast endpoint:
    # - hourly: precipitation (observed, past 7 days) + forecast (next 16 days)
    # - current_weather: true for the latest observation
    # - We request precipitation, precipitation_probability, weathercode
    # - forecast_days=7 covers the 6–24h prediction horizon (SRS.md Section 5)
    # -------------------------------------------------------------------------
    url = f"{OPEN_METEO_BASE}/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": [
            "precipitation",
            "precipitation_probability",
            "weathercode",
        ],
        "current_weather": "true",
        "past_days": 3,       # 72h antecedent data for antecedent_precipitation_index
        "forecast_days": 2,   # 48h forward for lead-time horizons up to t+24h
        "timezone": "Asia/Kolkata",
        "timeformat": "iso8601",
    }

    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.TimeoutException:
        raise RuntimeError(
            f"[ingest_rainfall] TIMEOUT after {TIMEOUT_SECONDS}s fetching Open-Meteo "
            f"for {name} ({lat}, {lon}). "
            "Per SRS.md Section 13: use cached_demo_snapshot.json as fallback. "
            "Do NOT substitute fake data (CLAUDE.md hard constraint)."
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"[ingest_rainfall] HTTP {e.response.status_code} from Open-Meteo for "
            f"{name} ({lat}, {lon}): {e.response.text}"
        )
    except httpx.RequestError as e:
        raise RuntimeError(
            f"[ingest_rainfall] Network error fetching Open-Meteo for {name}: {e}. "
            "Per SRS.md Section 13: use cached_demo_snapshot.json as fallback."
        )

    data = response.json()
    return data


def split_current_and_forecast(raw: dict, as_of: str) -> tuple[dict, dict]:
    """
    Split the Open-Meteo hourly series into:
      - 'current': all hourly entries up to (and including) as_of timestamp
      - 'forecast': all hourly entries strictly after as_of timestamp

    as_of should be an ISO8601 string (e.g. '2026-09-05T18:00').
    """
    times = raw.get("hourly", {}).get("time", [])
    precip = raw.get("hourly", {}).get("precipitation", [])

    # Find split index
    split_idx = 0
    for i, t in enumerate(times):
        if t <= as_of:
            split_idx = i + 1

    current_series = {
        "time": times[:split_idx],
        "precipitation_mm": precip[:split_idx],
    }
    forecast_series = {
        "time": times[split_idx:],
        "precipitation_mm": precip[split_idx:],
    }
    return current_series, forecast_series


def main() -> None:
    """
    Fetch rainfall data for all pilot locations and save to data/weather/.

    Exits with code 1 on any failure — never substitutes fake data.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
    fetched_at = datetime.now(timezone.utc).isoformat()

    all_current: list[dict] = []
    all_forecast: list[dict] = []

    for loc in PILOT_LOCATIONS:
        print(f"[ingest_rainfall] Fetching: {loc['name']} ({loc['lat']}, {loc['lon']}) ...")
        try:
            raw = fetch_rainfall_for_location(loc["lat"], loc["lon"], loc["name"])
        except RuntimeError as e:
            print(f"\nERROR: {e}", file=sys.stderr)
            print(
                "\nPipeline aborted. Fix the connection issue or use the cached demo snapshot "
                "(data/weather/cached_demo_snapshot.json) per SRS.md Section 13.\n",
                file=sys.stderr,
            )
            sys.exit(1)

        current_series, forecast_series = split_current_and_forecast(raw, now_iso)

        all_current.append({
            "location": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "current_weather": raw.get("current_weather", {}),
            "series": current_series,
        })
        all_forecast.append({
            "location": loc["name"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "series": forecast_series,
        })
        print(
            f"  -> {len(current_series['time'])} observed hours, "
            f"{len(forecast_series['time'])} forecast hours"
        )

    # Save current observations
    current_out = {
        "fetched_at": fetched_at,
        "data_source": "open_meteo_live",     # Phase 9 will set this to "cached_demo" on fallback
        "locations": all_current,
    }
    current_path = OUT_DIR / "rainfall_current.json"
    current_path.write_text(json.dumps(current_out, indent=2, ensure_ascii=False))
    print(f"\n[ingest_rainfall] Saved current observations -> {current_path}")

    # Save forecast series
    # NOTE: This forecast series is the input for lead-time computation in Phase 9
    # (SRS.md Section 12). Lead times are derived at hourly horizons only — t+1h,
    # t+2h, ... — never sub-hour interpolated.
    forecast_out = {
        "fetched_at": fetched_at,
        "data_source": "open_meteo_live",
        "locations": all_forecast,
    }
    forecast_path = OUT_DIR / "rainfall_forecast.json"
    forecast_path.write_text(json.dumps(forecast_out, indent=2, ensure_ascii=False))
    print(f"[ingest_rainfall] Saved forecast series     -> {forecast_path}")
    print("\n[ingest_rainfall] Done.")


if __name__ == "__main__":
    main()
