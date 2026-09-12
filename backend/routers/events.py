"""
backend/routers/events.py -- Phase 13: real historical multiregion events.

GET /events/map -- sourced historical flood/landslide events for the
multiregion dataset (see backend/seed_multiregion.py). NOT live model
output -- every entry carries data_source_note saying so explicitly
(CLAUDE.md: external-data-only content must be visibly labeled).
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from backend.database import get_db
from backend.models import EventMapEntry
from backend.seed_multiregion import REGIONS, load_terrain, H3_RES  # {region_key: (target_location, default_point)}
from ml.models.factor_of_safety import compute_factor_of_safety

import h3

TARGET_TO_REGION_KEY = {target_loc: key for key, (target_loc, _default_pt) in REGIONS.items()}

router = APIRouter(prefix="/events", tags=["events"])

ROOT = Path(__file__).resolve().parents[2]
TABPFN_PREDICTIONS_PATH = ROOT / "data" / "multiregion" / "model_ready" / "tabpfn" / "predictions.json"
CHRONOS_PREDICTIONS_PATH = ROOT / "data" / "multiregion" / "model_ready" / "chronos" / "predictions.json"
TABPFN_IMPORTANCE_PATH = ROOT / "data" / "multiregion" / "model_ready" / "tabpfn" / "feature_importance.json"

# region_key -> representative real GUARDIAN item_id, per
# data/multiregion/scripts/build_event_centered_samples.py's WSE_FILE_TO_POINTS
# and prepare_chronos_input.py's STATIONS. Picked the station at the SAME
# point used as this region's historical-panel default point where one
# exists (Rudraprayag, Chamoli, Darjeeling, Dhemaji); elsewhere the nearest
# real station within the district, labeled by its own name so it's never
# implied to be exactly at the pin (Idukki, Ribhoi, Sikkim). Nilgiris and
# Kullu have no real river station anywhere in the district -- omitted, not
# forced.
REGION_TO_CHRONOS_ITEM_ID = {
    "Idukki":      "Idamalayar_Reservoir",
    "Rudraprayag": "Rudraprayag_A",
    "Chamoli":     "Karnaprayag_A",
    "Ribhoi":      "Byrnihat",
    "Sikkim":      "Lachen",
    "Darjeeling":  "Melli",
    "Dhemaji":     "Dibrugarh",
}

# region_key -> soil_moisture_<slug>.json filename (data/multiregion/soil/),
# per ingest_soil_multiregion.py's real NASA POWER GWETROOT output.
SOIL_DIR = ROOT / "data" / "multiregion" / "soil"
REGION_TO_SOIL_SLUG = {
    "Idukki":      "idukki",
    "Rudraprayag": "rudraprayag",
    "Chamoli":     "chamoli",
    "Ribhoi":      "ribhoi",
    "Nilgiris":    "nilgiris",
    "Sikkim":      "sikkim_mangan",
    "Darjeeling":  "darjeeling_kalimpong",
    "Kullu":       "kullu",
    "Dhemaji":     "dhemaji",
}

# Same region_key -> slug map as soil (same filename convention:
# <kind>_<slug>.json in data/multiregion/<kind>/).
WEATHER_DIR = ROOT / "data" / "multiregion" / "weather"
REGION_TO_WEATHER_SLUG = REGION_TO_SOIL_SLUG

_soil_cache: dict[str, Optional[float]] = {}
_terrain_cache: Optional[dict] = None


def _point_name_for_hex(region_key: str, hex_id: str) -> Optional[str]:
    """Reverse-lookup a real terrain point's name from its hex_id -- same
    h3.latlng_to_cell computation seed_multiregion.py used to create the hex
    in the first place, never a guess."""
    global _terrain_cache
    if _terrain_cache is None:
        _terrain_cache = load_terrain()
    for point_name, feats in _terrain_cache.get(region_key, {}).items():
        lat, lon = feats.get("lat"), feats.get("lon")
        if lat is None or lon is None:
            continue
        if h3.latlng_to_cell(lat, lon, H3_RES) == hex_id:
            return point_name
    return None


def _parse_event_date(date_str: str) -> Optional[datetime]:
    """Real dataset date format is 'DD-MM-YYYY HH:mm' (India Flood Inventory
    v3) -- matches frontend HistoricalEventPanel.jsx's parseEventDate."""
    if not date_str:
        return None
    m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", date_str)
    if not m:
        return None
    day, month, year, hour, minute = m.groups()
    try:
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0))
    except ValueError:
        return None


def _latest_soil_for_region(region_key: str) -> Optional[float]:
    """Latest real NASA POWER GWETROOT reading (soil_saturation_ratio, SRS
    §10.1: used directly, never derived) for this region -- all named points
    in a region share one ~50km MERRA-2 grid cell (see the json's own
    resolution_note), so any one location's series is representative.
    Returns None if the file/series is missing -- never fabricated."""
    if region_key in _soil_cache:
        return _soil_cache[region_key]
    slug = REGION_TO_SOIL_SLUG.get(region_key)
    value = None
    if slug:
        path = SOIL_DIR / f"soil_moisture_{slug}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                locations = data.get("locations", [])
                if locations:
                    series = locations[0].get("gwetroot_hourly", {})
                    if series:
                        latest_key = max(series.keys())
                        value = series[latest_key]
            except (json.JSONDecodeError, OSError):
                value = None
    _soil_cache[region_key] = value
    return value


def _load_chronos_predictions() -> dict:
    if not CHRONOS_PREDICTIONS_PATH.exists():
        return {}
    try:
        return json.loads(CHRONOS_PREDICTIONS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _load_tabpfn_predictions() -> dict:
    """Real per-event TabPFN scores (Step 6a), if the inference has been run.
    Returns {} if not yet run -- never fabricates a placeholder score."""
    if not TABPFN_PREDICTIONS_PATH.exists():
        return {}
    try:
        return json.loads(TABPFN_PREDICTIONS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


@router.get("/tabpfn-importance")
def get_tabpfn_importance():
    """GET /events/tabpfn-importance -- GLOBAL permutation feature importance
    for the TabPFN model (Step 6c, compute_tabpfn_feature_importance.py).
    Same ranking for every event -- NOT per-prediction attribution, see
    caveat. Returns {} if the script hasn't been run yet -- never fabricates
    a placeholder ranking."""
    if not TABPFN_IMPORTANCE_PATH.exists():
        return {}
    try:
        return json.loads(TABPFN_IMPORTANCE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


@router.get("/map", response_model=List[EventMapEntry])
def get_events_map(bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat")):
    """GET /events/map?bbox=... -- all real historical events with a resolved hex."""
    tabpfn = _load_tabpfn_predictions()
    chronos = _load_chronos_predictions()

    with get_db() as conn:
        rows = conn.execute(
            """SELECT he.event_id, he.hex_id, he.date, he.type, he.severity, he.source,
                      he.coordinate_precision, he.region, h.static_features
               FROM historical_events he
               LEFT JOIN hexes h ON he.hex_id = h.hex_id
               WHERE he.hex_id IS NOT NULL"""
        ).fetchall()

    entries = []
    for row in rows:
        try:
            lat, lon = h3.cell_to_latlng(row["hex_id"])
        except Exception:
            continue
        if bbox:
            try:
                min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
                if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                    continue
            except Exception:
                pass
        try:
            static_features = json.loads(row["static_features"]) if row["static_features"] else None
        except (json.JSONDecodeError, TypeError):
            static_features = None
        pred = tabpfn.get(row["event_id"])

        region_key = TARGET_TO_REGION_KEY.get(row["region"])
        item_id = REGION_TO_CHRONOS_ITEM_ID.get(region_key)
        river = chronos.get(item_id) if item_id else None

        # Real Phase 5 factor-of-safety (SRS §10.1: beta=slope_deg,
        # m=soil_saturation_ratio, no Monte Carlo) using this point's real
        # SRTM slope + the region's latest real GWETROOT reading. NOT this
        # historical event's own at-disaster soil conditions -- a present-day
        # estimate at a real terrain point, always disclosed as such.
        slope_deg = static_features.get("slope_deg") if static_features else None
        soil_val = _latest_soil_for_region(region_key) if region_key else None
        fs = compute_factor_of_safety(slope_deg, soil_val)

        entries.append(EventMapEntry(
            event_id=row["event_id"],
            hex_id=row["hex_id"],
            region=row["region"] or "Wayanad",
            lat=lat, lon=lon,
            date=row["date"],
            type=row["type"],
            severity=row["severity"],
            source=row["source"],
            coordinate_precision=row["coordinate_precision"] or "village-level",
            static_features=static_features,
            tabpfn_risk_score=pred["risk_score"] if pred else None,
            tabpfn_tier=pred["tier"] if pred else None,
            tabpfn_caveat=pred["caveat"] if pred else None,
            chronos_station=item_id if river else None,
            chronos_last_observed_time=river["last_observed_time"] if river else None,
            chronos_last_observed_value_m=river["last_observed_value_m"] if river else None,
            chronos_forecast_median_m=river["forecast_median_m"] if river else None,
            chronos_forecast_low_m=river["forecast_low_m"] if river else None,
            chronos_forecast_high_m=river["forecast_high_m"] if river else None,
            chronos_prediction_length_steps=river["prediction_length_steps"] if river else None,
            chronos_caveat=river["caveat"] if river else None,
            factor_of_safety=fs["factor_of_safety"],
            factor_of_safety_min=fs["factor_of_safety_min"],
            factor_of_safety_max=fs["factor_of_safety_max"],
            factor_of_safety_note=(
                "Present-day estimate: this point's real slope + the region's latest real "
                "NASA POWER soil reading -- not this historical event's own at-disaster conditions."
                if not fs["missing_inputs"] else
                f"Factor of safety unavailable -- missing real: {', '.join(fs['missing_inputs'])}"
            ),
        ))
    return entries


@router.get("/{event_id}/rainfall-window")
def get_event_rainfall_window(event_id: str):
    """GET /events/{event_id}/rainfall-window -- real hourly rainfall (mm)
    for the 24h immediately before this specific real event's recorded
    timestamp, sourced from the same ingested ERA5 series used throughout
    Phase 13 (data/multiregion/weather/rainfall_historical_<region>.json).
    Returns an empty series (with an honest note) rather than a fabricated
    one when real coverage doesn't reach this event's date -- the ingestion
    window covers full monsoon seasons per year, not arbitrary dates."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT event_id, hex_id, date, region FROM historical_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No event {event_id}")

    event_dt = _parse_event_date(row["date"])
    region_key = TARGET_TO_REGION_KEY.get(row["region"])
    point_name = _point_name_for_hex(region_key, row["hex_id"]) if region_key else None

    if event_dt is None or region_key is None or point_name is None:
        return {
            "event_id": event_id, "event_date": row["date"], "region": row["region"],
            "point_name": point_name, "series": [],
            "note": "Could not resolve this event to a real date/terrain point -- no window to show.",
        }

    slug = REGION_TO_WEATHER_SLUG.get(region_key)
    path = WEATHER_DIR / f"rainfall_historical_{slug}.json" if slug else None
    if not path or not path.exists():
        return {
            "event_id": event_id, "event_date": row["date"], "region": row["region"],
            "point_name": point_name, "series": [],
            "note": f"No real rainfall series file for region '{row['region']}'.",
        }

    try:
        data = json.loads(path.read_text())
        loc = next((l for l in data.get("locations", []) if l.get("location") == point_name), None)
    except (json.JSONDecodeError, OSError):
        loc = None

    if loc is None:
        return {
            "event_id": event_id, "event_date": row["date"], "region": row["region"],
            "point_name": point_name, "series": [],
            "note": f"No real rainfall series for point '{point_name}' in this region's ingested data.",
        }

    times = loc.get("series", {}).get("time", [])
    precip = loc.get("series", {}).get("precipitation_mm", [])
    window_start = event_dt - timedelta(hours=24)

    series = []
    for t_str, p in zip(times, precip):
        try:
            t = datetime.fromisoformat(t_str)
        except ValueError:
            continue
        if window_start <= t <= event_dt:
            series.append({"time": t.isoformat(), "rainfall_mm": p})
    series.sort(key=lambda x: x["time"])

    note = (
        f"Real ERA5-derived hourly rainfall at {point_name}, the {24} hours before this event's "
        "recorded timestamp -- not a model prediction."
        if series else
        f"Real rainfall series exists for {point_name} but has no coverage in the 24h before "
        f"{row['date']} (ingestion covers full monsoon-season windows per year, not every date)."
    )
    return {
        "event_id": event_id, "event_date": row["date"], "region": row["region"],
        "point_name": point_name, "series": series, "note": note,
    }
