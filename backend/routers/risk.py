"""
backend/routers/risk.py -- SRS.md Section 15 risk endpoints.

GET /risk/{hex_id}
GET /risk/map
GET /risk/{hex_id}/history
GET /risk/{hex_id}/inundation   (gated in code: tier >= Orange)
GET /risk/{hex_id}/uncertainty
"""

from __future__ import annotations
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from backend.database import get_db
from backend.models import RiskResponse, RiskMapEntry, RiskHistoryEntry, UncertaintyResponse
from backend.risk_engine import compute_and_store_risk

router = APIRouter(prefix="/risk", tags=["risk"])

ORANGE_RED = {"Orange", "Red"}


VILLAGE_CENTROIDS = [
    ("Mundakkai", 11.5185, 76.0524),
    ("Chooralmala", 11.5143, 76.0498),
    ("Attamala", 11.5220, 76.0570),
    ("Punjirimattom", 11.5100, 76.0450),
]

def _nearest_village(lat: float, lon: float) -> str:
    best_dist = float("inf")
    best_name = "Wayanad Sector"
    for name, vlat, vlon in VILLAGE_CENTROIDS:
        d = (lat - vlat)**2 + (lon - vlon)**2
        if d < best_dist:
            best_dist = d
            best_name = name
    return best_name

from backend.repository import get_risk_map_data as _get_risk_map_data


@router.get("/map", response_model=List[RiskMapEntry])
def get_risk_map(
    region: Optional[str] = Query(None, description="Region code e.g. wayanad-kl"),
    bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat")
):
    """GET /risk/map?region=...&bbox=... -- all hex risk scores with rich explainability attributes."""
    data = _get_risk_map_data(region_code=region, bbox=bbox)
    return [RiskMapEntry(**d) for d in data]



@router.get("/{hex_id}", response_model=RiskResponse)
def get_risk(hex_id: str):
    """GET /risk/{hex_id} -- current risk score for a hex."""
    from datetime import datetime, timezone

    # Serve the stored score while it is fresh (default 10 min; the scoring cycle is 15 min) instead of
    # recomputing from live weather on every click (4-12 s, longer than the UI's 8 s timeout).
    import os
    from backend import risk_engine
    ttl_s = float(os.environ.get("HYDRASENSE_RISK_TTL_S", "600"))
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM risk_scores WHERE hex_id=? ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()

    if row is not None:
        try:
            row_ts = datetime.fromisoformat(row["timestamp"])
            age_s = (datetime.now(timezone.utc) - row_ts).total_seconds()
            if age_s < ttl_s:
                mem = risk_engine.LAST_RESULTS.get(hex_id)
                if mem and mem.get("timestamp") == row["timestamp"]:
                    return RiskResponse(**mem)                       # real FS values from this process
                contribs = json.loads(row["feature_contributions"] or "[]")
                return RiskResponse(
                    hex_id=row["hex_id"],
                    timestamp=row["timestamp"],
                    risk_score=row["risk_score"],
                    tier=row["tier"],
                    confidence_score=row["confidence_score"],
                    lead_time_min=row["lead_time_min"],
                    lead_time_basis=row["lead_time_basis"] or "forecast_projection",
                    top_contributing_features=contribs,              # FS left None: not stored, not invented
                    data_source=row["data_source"] or "live",
                )
        except Exception:
            pass

    result = compute_and_store_risk(hex_id)
    if result is not None:
        return RiskResponse(**result)

    if row is not None:
        contribs = json.loads(row["feature_contributions"] or "[]")
        return RiskResponse(
            hex_id=row["hex_id"],
            timestamp=row["timestamp"],
            risk_score=row["risk_score"],
            tier=row["tier"],
            confidence_score=row["confidence_score"],
            lead_time_min=row["lead_time_min"],
            lead_time_basis=row["lead_time_basis"] or "model_unavailable",
            top_contributing_features=contribs,
            data_source=row["data_source"] or "cached_demo",
        )

    raise HTTPException(status_code=404, detail=f"No risk score for {hex_id}")


@router.get("/{hex_id}/history", response_model=List[RiskHistoryEntry])
def get_risk_history(hex_id: str, limit: int = Query(48, ge=1, le=500)):
    """GET /risk/{hex_id}/history -- time series of risk_score (1D trend view)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM risk_scores WHERE hex_id=? ORDER BY timestamp DESC LIMIT ?",
            (hex_id, limit)
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No history for hex {hex_id}")
    keys = rows[0].keys()
    opt = lambda r, k: r[k] if k in keys else None
    return [RiskHistoryEntry(timestamp=r["timestamp"], risk_score=r["risk_score"], tier=r["tier"],
                             index_landslide=opt(r, "index_landslide"), index_flood=opt(r, "index_flood"),
                             rainfall_24h=opt(r, "rainfall_24h")) for r in reversed(rows)]


@router.get("/{hex_id}/inundation")
def get_inundation(hex_id: str):
    """
    GET /risk/{hex_id}/inundation -- simplified 2D inundation raster.
    GATED IN CODE: only returns data if tier >= Orange (SRS.md Section 15).
    Returns 403 for Green/Yellow hexes.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT tier FROM risk_scores WHERE hex_id=? ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"No risk score for hex {hex_id}")

    if row["tier"] not in ORANGE_RED:
        raise HTTPException(
            status_code=403,
            detail=f"Inundation raster only available for Orange/Red tier hexes. "
                   f"Current tier: {row['tier']}"
        )

    # Simplified inundation: return hex geometry + affected area estimate
    # Full DEM-based inundation is Phase 3 terrain territory; this is the stub
    # that Phase 12 (frontend) can render.
    import h3 as _h3
    boundary = _h3.cell_to_boundary(hex_id)
    return {
        "hex_id": hex_id,
        "tier": row["tier"],
        "inundation_polygon": [{"lat": lat, "lon": lon} for lat, lon in boundary],
        "area_km2": 0.74,   # H3 res-8 hex area is ~0.74 km2
        "note": "simplified hex-boundary inundation; DEM-based raster pending Phase 3 terrain run",
    }


@router.get("/{hex_id}/uncertainty", response_model=UncertaintyResponse)
def get_uncertainty(hex_id: str):
    """GET /risk/{hex_id}/uncertainty -- FS band + confidence breakdown."""
    with get_db() as conn:
        obs_row = conn.execute(
            "SELECT dynamic_features FROM observations "
            "WHERE hex_id=? ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()
        rs_row = conn.execute(
            "SELECT confidence_score FROM risk_scores "
            "WHERE hex_id=? ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()

    fs = fs_min = fs_max = None
    band_note = "factor_of_safety unavailable -- this hex has no real terrain (static_features) recorded yet"
    if obs_row:
        try:
            feats = json.loads(obs_row["dynamic_features"] or "{}")
            fs = feats.get("factor_of_safety")
            fs_min = feats.get("factor_of_safety_min")
            fs_max = feats.get("factor_of_safety_max")
            if fs_min is not None:
                band_note = f"FS band [{fs_min:.2f}, {fs_max:.2f}]"
        except Exception:
            pass

    confidence = rs_row["confidence_score"] if rs_row else 0.0
    return UncertaintyResponse(
        hex_id=hex_id,
        factor_of_safety=fs,
        factor_of_safety_min=fs_min,
        factor_of_safety_max=fs_max,
        confidence_score=confidence,
        band_note=band_note,
    )
