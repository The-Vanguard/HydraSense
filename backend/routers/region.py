"""
backend/routers/region.py
POST /region/resolve — Autonomous Region Onboarding endpoint (Final.md §15.5 / §6).

This endpoint is the gateway to the Autonomous Onboarding Pipeline.
It accepts a place name (or lat/lon) and returns:
  - resolved boundary + admin breadcrumb
  - list of H3 hex IDs in the region
  - has_local_calibration flag
  - per-layer data source status
  - region_code to use in subsequent API calls

Caching: if the region is already onboarded (GeoPackage exists), the result
is returned from cache without re-running the full pipeline. Use ?force=true
to re-onboard.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import time

from backend.onboarding.pipeline import (
    run_pipeline, region_is_onboarded,  # noqa: F401 — re-exported
    ALL_REGIONS, REGION_BY_CODE,
)
from backend.onboarding.geopackage import (
    load_region_gpkg, list_onboarded_regions, get_region_hex_ids,
)

router = APIRouter(prefix="/region", tags=["region"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class BoundaryInfo(BaseModel):
    region_code:     str
    display_name:    str
    admin_breadcrumb: list[str]
    state:           str
    district:        str
    bbox:            dict


class RegionResolveResponse(BaseModel):
    region_code:           str
    label:                 str
    success:               bool
    hex_count:             int
    h3_resolution:         int
    has_local_calibration: bool
    boundary:              Optional[BoundaryInfo]
    data_sources:          dict
    elapsed_s:             float
    warnings:              list[str]
    error:                 Optional[str]
    # Sample of hex IDs (first 20 — full list via GET /region/{region_code}/hexes)
    hex_ids_sample:        list[str]


class RegionSummary(BaseModel):
    region_code:  str
    label:        str
    zone:         str
    onboarded:    bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/resolve", response_model=RegionResolveResponse)
async def resolve_region(
    query: str = Query(..., description="Place name e.g. 'Wayanad Kerala India' or 'Rudraprayag'"),
    force: bool = Query(False, description="Force re-onboarding even if region already exists"),
):
    """
    Resolve a place name to an H3 grid and onboard it through the
    Autonomous Region Onboarding Pipeline.

    If the region is already onboarded (GeoPackage exists), returns cached
    result immediately. Use force=true to reprocess.
    """
    t0 = time.perf_counter()

    # Check if any known region matches the query (fast-path)
    matched_region = None
    query_lower = query.lower()
    for r in ALL_REGIONS:
        if (r["region_code"].replace("-", " ") in query_lower or
                any(part in query_lower for part in r["query"].lower().split()[:2])):
            matched_region = r
            break

    region_code = matched_region["region_code"] if matched_region else None

    # Fast path: already onboarded and not forcing rerun
    if region_code and region_is_onboarded(region_code) and not force:
        hex_ids = get_region_hex_ids(region_code)
        meta    = matched_region
        return RegionResolveResponse(
            region_code=region_code,
            label=meta["label"],
            success=True,
            hex_count=len(hex_ids),
            h3_resolution=8,   # default; actual stored in GeoPackage
            has_local_calibration=True,   # will be read from GeoPackage in full impl
            boundary=None,
            data_sources={"terrain": "cached", "soil": "cached", "land_cover": "cached"},
            elapsed_s=round(time.perf_counter() - t0, 2),
            warnings=["Returned from cache. Use force=true to re-onboard."],
            error=None,
            hex_ids_sample=hex_ids[:20],
        )

    # Full pipeline run
    result = run_pipeline(query=query, region_code=region_code, force_rerun=force)

    boundary_info = None
    if result.boundary:
        boundary_info = BoundaryInfo(
            region_code=result.boundary.region_code,
            display_name=result.boundary.display_name,
            admin_breadcrumb=result.boundary.admin_breadcrumb,
            state=result.boundary.state,
            district=result.boundary.district,
            bbox=result.boundary.bbox,
        )

    hex_ids = get_region_hex_ids(result.region_code)

    return RegionResolveResponse(
        region_code=result.region_code,
        label=result.label,
        success=result.success,
        hex_count=result.hex_count,
        h3_resolution=result.h3_resolution,
        has_local_calibration=result.has_local_calibration,
        boundary=boundary_info,
        data_sources=result.data_sources,
        elapsed_s=round(result.elapsed_s, 2),
        warnings=result.warnings,
        error=result.error,
        hex_ids_sample=hex_ids[:20],
    )


@router.get("/list", response_model=list[RegionSummary])
async def list_regions():
    """
    List all 10 supported regions and their onboarding status.
    """
    onboarded = set(list_onboarded_regions())
    return [
        RegionSummary(
            region_code=r["region_code"],
            label=r["label"],
            zone=r["zone"],
            onboarded=r["region_code"] in onboarded,
        )
        for r in ALL_REGIONS
    ]


@router.get("/{region_code}/hexes")
async def get_region_hexes(region_code: str):
    """Return all H3 hex IDs for an onboarded region."""
    hex_ids = get_region_hex_ids(region_code)
    if not hex_ids:
        raise HTTPException(status_code=404,
                            detail=f"Region '{region_code}' not found. Run POST /region/resolve?query=... first.")
    return {"region_code": region_code, "hex_count": len(hex_ids), "hex_ids": hex_ids}


@router.get("/{region_code}/static-features/{hex_id}")
async def get_hex_static_features(region_code: str, hex_id: str):
    """Return static features for a single hex from the GeoPackage."""
    from backend.onboarding.geopackage import get_hex_static_features
    feats = get_hex_static_features(region_code, hex_id)
    if feats is None:
        raise HTTPException(status_code=404,
                            detail=f"Hex {hex_id} not found in region {region_code}")
    # Remove geometry (not JSON-serializable without conversion)
    feats.pop("geometry", None)
    return feats
