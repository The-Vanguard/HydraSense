"""
backend/routers/events.py -- Phase 13: real historical multiregion events.

GET /events/map -- sourced historical flood/landslide events for the
multiregion dataset (see backend/seed_multiregion.py). NOT live model
output -- every entry carries data_source_note saying so explicitly
(CLAUDE.md: external-data-only content must be visibly labeled).
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Query
from backend.database import get_db
from backend.models import EventMapEntry
from backend.seed_multiregion import REGIONS  # {region_key: (target_location, default_point)}
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

_soil_cache: dict[str, Optional[float]] = {}


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
