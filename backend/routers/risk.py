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


@router.get("/map", response_model=List[RiskMapEntry])
def get_risk_map(bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat")):
    """GET /risk/map?bbox=... -- all hex risk scores in bounding box."""
    with get_db() as conn:
        # Get latest score per hex (SQLite window-function compatible)
        rows = conn.execute("""
            SELECT rs.hex_id, rs.risk_score, rs.tier, rs.data_source, rs.timestamp,
                   h.geom
            FROM risk_scores rs
            JOIN (
                SELECT hex_id, MAX(timestamp) AS max_ts FROM risk_scores GROUP BY hex_id
            ) latest ON rs.hex_id = latest.hex_id AND rs.timestamp = latest.max_ts
            LEFT JOIN hexes h ON rs.hex_id = h.hex_id
        """).fetchall()

    entries = []
    for row in rows:
        # Basic bbox filter if provided (parse geom centroid from hex_id via h3)
        if bbox:
            try:
                min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
                import h3 as _h3
                lat, lon = _h3.cell_to_latlng(row["hex_id"])
                if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                    continue
            except Exception:
                pass  # if bbox parse fails, include all
        entries.append(RiskMapEntry(
            hex_id=row["hex_id"],
            risk_score=row["risk_score"],
            tier=row["tier"],
            data_source=row["data_source"] or "live",
        ))
    return entries


@router.get("/{hex_id}", response_model=RiskResponse)
def get_risk(hex_id: str):
    """GET /risk/{hex_id} -- latest risk score for a hex."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM risk_scores WHERE hex_id=? ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()
    if row is None:
        # No cached score -- compute on demand
        result = compute_and_store_risk(hex_id)
        if result is None:
            raise HTTPException(status_code=404,
                detail=f"No risk score for {hex_id} and model not available")
        return RiskResponse(**result)

    contribs = json.loads(row["feature_contributions"] or "[]")
    return RiskResponse(
        hex_id=row["hex_id"],
        timestamp=row["timestamp"],
        risk_score=row["risk_score"],
        tier=row["tier"],
        confidence_score=row["confidence_score"],
        lead_time_min=row["lead_time_min"],
        lead_time_basis=row["lead_time_basis"] or "pending_phase_9",
        top_contributing_features=contribs,
        data_source=row["data_source"] or "live",
    )


@router.get("/{hex_id}/history", response_model=List[RiskHistoryEntry])
def get_risk_history(hex_id: str, limit: int = Query(48, ge=1, le=500)):
    """GET /risk/{hex_id}/history -- time series of risk_score (1D trend view)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT timestamp, risk_score, tier FROM risk_scores "
            "WHERE hex_id=? ORDER BY timestamp DESC LIMIT ?",
            (hex_id, limit)
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No history for hex {hex_id}")
    return [RiskHistoryEntry(timestamp=r["timestamp"],
                             risk_score=r["risk_score"],
                             tier=r["tier"]) for r in reversed(rows)]


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

    fs_min = fs_max = None
    band_note = "factor_of_safety_min/max unavailable until Phase 3 DEM rasters run"
    if obs_row:
        try:
            feats = json.loads(obs_row["dynamic_features"] or "{}")
            fs_min = feats.get("factor_of_safety_min")
            fs_max = feats.get("factor_of_safety_max")
            if fs_min is not None:
                band_note = f"FS band [{fs_min:.2f}, {fs_max:.2f}]"
        except Exception:
            pass

    confidence = rs_row["confidence_score"] if rs_row else 0.0
    return UncertaintyResponse(
        hex_id=hex_id,
        factor_of_safety_min=fs_min,
        factor_of_safety_max=fs_max,
        confidence_score=confidence,
        band_note=band_note,
    )
