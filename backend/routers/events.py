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

import h3

router = APIRouter(prefix="/events", tags=["events"])

ROOT = Path(__file__).resolve().parents[2]
TABPFN_PREDICTIONS_PATH = ROOT / "data" / "multiregion" / "model_ready" / "tabpfn" / "predictions.json"


def _load_tabpfn_predictions() -> dict:
    """Real per-event TabPFN scores (Step 6a), if the inference has been run.
    Returns {} if not yet run -- never fabricates a placeholder score."""
    if not TABPFN_PREDICTIONS_PATH.exists():
        return {}
    try:
        return json.loads(TABPFN_PREDICTIONS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


@router.get("/map", response_model=List[EventMapEntry])
def get_events_map(bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat")):
    """GET /events/map?bbox=... -- all real historical events with a resolved hex."""
    tabpfn = _load_tabpfn_predictions()

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
        ))
    return entries
