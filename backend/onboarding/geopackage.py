"""
backend/onboarding/geopackage.py
GeoPackage (.gpkg) read/write for per-region spatial data (Final.md §15.3).

One .gpkg file per onboarded region stores the H3 hex grid + static features
as a GeoDataFrame. This gives us:
  - Spatial indexing (R-tree) for bbox queries — no full-table scan
  - Single portable file per region — clean artifact for the demo shortlist
  - GeoPandas native I/O — no separate server process

Tables stored in each .gpkg:
  hexes_static  — one row per H3 hex with all static features + geometry

The existing hydrasense.db (row-level operational data: risk_scores, alerts,
observations, shelters) remains unchanged — it is the live-update store.
The .gpkg is the spatial-index store for hex geometry and static features.

Final.md §15.3: "a single .gpkg file per onboarded region"
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT     = Path(__file__).resolve().parents[2]
GPKG_DIR = ROOT / "data" / "regions"

GPKG_DIR.mkdir(parents=True, exist_ok=True)


def _gpkg_path(region_code: str) -> Path:
    return GPKG_DIR / f"{region_code}.gpkg"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save_region_gpkg(region_code: str, grid_result, boundary_result=None) -> Path:
    """
    Save an H3GridResult to a GeoPackage file.

    Creates a GeoDataFrame with:
      - geometry column: H3 hex boundary as a shapely Polygon
      - one column per static feature
      - region_code, h3_resolution columns
      - provenance column (Gap Analysis §0.2 Phase 0) — REAL_VALIDATED when
        derived from a real DEM, SIMULATED when terrain was unavailable.
        This is a first-class column (not buried in JSON) so the file is
        directly queryable from QGIS and geopandas without JSON parsing.

    Args:
        region_code: slug
        grid_result: H3GridResult from h3_grid.build_h3_grid()
        boundary_result: BoundaryResult (for metadata columns)

    Returns: path to the written .gpkg file
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Polygon
    except ImportError:
        print("      WARNING: geopandas not found, skipping GeoPackage write in this environment.")
        return _gpkg_path(region_code)

    import h3
    gpkg_path = _gpkg_path(region_code)

    rows = []
    for hex_id in grid_result.hex_ids:
        feats = grid_result.hex_features.get(hex_id, {})

        # Build boundary polygon from H3 boundary vertices
        boundary = h3.cell_to_boundary(hex_id)   # list of (lat, lon) tuples
        polygon  = Polygon([(lon, lat) for lat, lon in boundary])

        lat, lon = h3.cell_to_latlng(hex_id)

        row = {
            "hex_id":          hex_id,
            "region_code":     region_code,
            "h3_resolution":   grid_result.resolution,
            "centroid_lat":    lat,
            "centroid_lon":    lon,
            "geometry":        polygon,
            # Static features
            "slope_deg":                  feats.get("slope_deg"),
            "aspect":                     feats.get("aspect"),
            "TWI":                        feats.get("TWI"),
            "TRI":                        feats.get("TRI"),
            "elevation":                  feats.get("elevation"),
            "distance_to_stream_m":       feats.get("distance_to_stream_m"),
            "drainage_density":           feats.get("drainage_density"),
            "flow_accumulation":          feats.get("flow_accumulation"),
            "hand_m":                     feats.get("hand_m"),
            "curve_number":               feats.get("curve_number"),
            "land_use_class":             feats.get("land_use_class"),
            "ndvi_mean":                  feats.get("ndvi_mean"),
            "historical_event_count_500m": feats.get("historical_event_count_500m", 0),
            "gsi_susceptibility_class":   feats.get("gsi_susceptibility_class", "unknown"),
            "has_local_calibration":      int(feats.get("has_local_calibration", False)),
            # Gap Analysis §0.2 Phase 0: provenance column — first-class field,
            # not buried in JSON, so the .gpkg is queryable directly from QGIS.
            # REAL_VALIDATED = terrain from real DEM; SIMULATED = no DEM available.
            "provenance":                 feats.get("provenance", "SIMULATED"),
        }
        # Metadata from boundary resolution
        if boundary_result:
            row["display_name"]     = boundary_result.display_name[:200]
            row["admin_state"]      = boundary_result.state
            row["admin_district"]   = boundary_result.district
        rows.append(row)

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    gdf.to_file(str(gpkg_path), driver="GPKG", layer="hexes_static")

    print(f"    GeoPackage: {gpkg_path.name} — {len(rows)} hexes written")
    return gpkg_path


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_region_gpkg(region_code: str, bbox: Optional[dict] = None):
    """
    Load the static feature GeoDataFrame for a region.
    If bbox is provided, returns only hexes whose centroids fall within the bbox
    (uses spatial index for efficiency — no full-table scan).

    Returns: GeoDataFrame | None
    """
    try:
        import geopandas as gpd
        from shapely.geometry import box
    except ImportError:
        return None

    gpkg_path = _gpkg_path(region_code)
    if not gpkg_path.exists():
        return None

    gdf = gpd.read_file(str(gpkg_path), layer="hexes_static")
    if gdf.empty:
        return None

    if bbox:
        clip_box = box(bbox["west"], bbox["south"], bbox["east"], bbox["north"])
        gdf = gdf[gdf.geometry.intersects(clip_box)]

    return gdf


def list_onboarded_regions() -> list[str]:
    """Return list of region_codes that have a .gpkg file."""
    return sorted(p.stem for p in GPKG_DIR.glob("*.gpkg"))


def region_is_onboarded(region_code: str) -> bool:
    return _gpkg_path(region_code).exists()


def get_region_hex_ids(region_code: str) -> list[str]:
    """Return all hex IDs for an onboarded region (fast — reads only hex_id column)."""
    try:
        import geopandas as gpd
    except ImportError:
        return []

    gpkg_path = _gpkg_path(region_code)
    if not gpkg_path.exists():
        return []
    try:
        gdf = gpd.read_file(str(gpkg_path), layer="hexes_static", columns=["hex_id"])
        return list(gdf["hex_id"])
    except Exception:
        return []


def get_hex_static_features(region_code: str, hex_id: str) -> Optional[dict]:
    """
    Return static features for one hex from the GeoPackage.
    Uses spatial index — does not scan the full file.
    """
    gdf = load_region_gpkg(region_code)
    if gdf is None:
        return None
    row = gdf[gdf["hex_id"] == hex_id]
    if row.empty:
        return None
    return row.iloc[0].to_dict()
