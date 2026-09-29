"""
backend/routers/evacuation.py -- GET /evacuation/{village_id}?region=...  (v2 Sec. 11.2, MVP advisory)

Nearest shelters to the village centroid by STRAIGHT-LINE distance.  This is not a routed path and
it does not check blocked roads or the inundation footprint: the response says so.  Shelters
farther than MAX_SHELTER_KM are never offered (the seeded shelter list covers Wayanad only, so a
village elsewhere gets "none within range", not a shelter hundreds of km away).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, HTTPException, Query

from backend.database import get_db
from backend.routers import village as village_api

router = APIRouter(prefix="/evacuation", tags=["evacuation"])
MAX_SHELTER_KM = 30.0
BASIS = ("straight-line distance from the village centroid: not a routed path, not blockage-aware "
         "(v2 Sec. 11.2 routing over the OSM road network is not built)")


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def load_shelters() -> list[dict]:
    with get_db() as conn:
        return [dict(r) for r in conn.execute("SELECT shelter_id, name, lat, lon FROM shelters").fetchall()]


@router.get("/{village_id}")
def evacuation_advisory(village_id: str, region: str = Query(...), limit: int = Query(3, ge=1, le=10)):
    layers = village_api.load_region_layers(region)
    v = next((x for x in layers.villages if x["village_id"] == village_id), None)
    if v is None:
        raise HTTPException(404, detail=f"village '{village_id}' not found in region '{region}'")
    c = v["geometry"].centroid
    shelters = load_shelters()
    near = sorted(
        ({**s, "distance_km": round(_haversine_km(c.y, c.x, s["lat"], s["lon"]), 2)} for s in shelters),
        key=lambda s: s["distance_km"])
    near = [s for s in near if s["distance_km"] <= MAX_SHELTER_KM][:limit]
    out = dict(village_id=village_id, region=region, basis=BASIS, advisory_only=True,
               blocked_roads_checked=False, shelters=near, shelters_in_database=len(shelters),
               reference="HydraSense_v2 Sec. 11.2")
    if not near:
        out["note"] = (f"no shelter within {MAX_SHELTER_KM:.0f} km in the shelter list "
                       f"({len(shelters)} listed): none offered")
    return out
