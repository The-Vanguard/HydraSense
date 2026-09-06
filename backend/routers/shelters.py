"""
backend/routers/shelters.py -- GET /shelters/nearest/{hex_id} (SRS.md Section 15).
Simple distance-sort against static shelters table. NOT a routing engine.
"""
import math
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, HTTPException
from backend.database import get_db
from backend.models import ShelterResponse
import h3

router = APIRouter(prefix="/shelters", tags=["shelters"])


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))


@router.get("/nearest/{hex_id}", response_model=List[ShelterResponse])
def get_nearest_shelters(hex_id: str, limit: int = 3):
    """
    GET /shelters/nearest/{hex_id} -- nearest shelters by straight-line distance.
    Simple distance sort, NOT a routing engine (SRS.md Section 15).
    """
    try:
        hex_lat, hex_lon = h3.cell_to_latlng(hex_id)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid hex_id: {hex_id}")

    with get_db() as conn:
        rows = conn.execute("SELECT * FROM shelters").fetchall()

    if not rows:
        raise HTTPException(status_code=404,
            detail="No shelters in database. Run: python backend/seed.py")

    shelters_with_dist = []
    for row in rows:
        dist = _haversine_km(hex_lat, hex_lon, row["lat"], row["lon"])
        shelters_with_dist.append({
            "shelter_id":  row["shelter_id"],
            "name":        row["name"],
            "hex_id":      row["hex_id"],
            "lat":         row["lat"],
            "lon":         row["lon"],
            "distance_km": round(dist, 3),
        })

    shelters_with_dist.sort(key=lambda x: x["distance_km"])
    return [ShelterResponse(**s) for s in shelters_with_dist[:limit]]
