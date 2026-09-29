"""
backend/onboarding/catchments.py
Step 9 of the Autonomous Region Onboarding Pipeline (Gap Analysis §A3).

Micro-catchment delineation using pysheds from the real SRTM DEM.
Writes a 'catchments' layer to the region's GeoPackage.

Algorithm (revised: stream-link catchments; see stream_links.py for why pysheds' own
catchment()/fill_depressions() are no longer used):
  1. Load the DEM raster via pysheds Grid.
  2. Fill depressions (morphological reconstruction) and resolve flats.
  3. Compute D8 flow direction.
  4. Compute D8 flow accumulation.
  5. Extract stream network by thresholding accumulation
     (>= ACCUMULATION_THRESHOLD_CELLS).
  6. Delineate sub-catchments from stream outlet points.
  7. Compute per-catchment attributes:
       - area_km2          (polygon area)
       - upslope_reach_km  (max flow-path length from divide to outlet)
       - mean_slope_deg    (mean slope within polygon)
       - outlet_hex_id     (H3 res-8 cell of the outlet point)
  8. Append the 'catchments' layer to the region GeoPackage.

Provenance: every row is tagged REAL_VALIDATED when derived from the real DEM;
SIMULATED when the DEM was not available and we return a graceful fallback.

Dependencies: pysheds>=0.4, geopandas>=0.14, shapely>=2.0, rasterio>=1.3, h3>=4.0
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Gap Analysis §0.2: provenance policy
from backend.provenance import ProvenanceTag

ROOT     = Path(__file__).resolve().parents[2]
GPKG_DIR = ROOT / "data" / "regions"

# Flow accumulation threshold: cells with >= this many upstream cells are
# treated as stream channels.  At SRTM 30m resolution, ~500 cells ≈ 0.45 km².
# Adjust downward for very small catchments (res-9 regions).
ACCUMULATION_THRESHOLD_CELLS: int = 500

# Maximum number of catchments to delineate per region (prevents OOM on
# very large/flat regions where the stream network is extremely dense).
MAX_CATCHMENTS: int = 5000

# Stream-link catchments smaller than this are not written (v2 Sec. 5.2 wants settlement-scale units).
MIN_CATCHMENT_KM2: float = 0.05


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CatchmentResult:
    region_code:      str
    success:          bool
    catchment_count:  int = 0
    gpkg_path:        Optional[Path] = None
    error:            Optional[str] = None
    warnings:         list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def delineate_catchments(
    region_code: str,
    dem_path: Optional[Path],
    gpkg_path: Path,
    bbox: dict,
) -> CatchmentResult:
    """
    Delineate micro-catchments from the region DEM and write them as the
    'catchments' layer in the region's GeoPackage.

    Args:
        region_code: slug (e.g. "wayanad-kl")
        dem_path:    path to the SRTM DEM GeoTIFF for this region.
                     If None or missing, returns a graceful SIMULATED fallback.
        gpkg_path:   path to the region's .gpkg file (must already exist).
        bbox:        bounding box dict {south, north, west, east} in WGS84.

    Returns:
        CatchmentResult
    """
    warns: list[str] = []

    # ── Dependency guard ───────────────────────────────────────────────────
    try:
        import numpy as np
        import rasterio
        import geopandas as gpd
        import h3
        from shapely.geometry import shape, mapping, Polygon, MultiPolygon
        from shapely.ops import unary_union
    except ImportError as e:
        return CatchmentResult(
            region_code=region_code, success=False,
            error=f"Missing dependency for catchment delineation: {e}. "
                  f"Install: pip install pysheds geopandas rasterio shapely"
        )

    try:
        from pysheds.grid import Grid
    except ImportError:
        return CatchmentResult(
            region_code=region_code, success=False,
            error="pysheds not installed. Run: pip install pysheds>=0.4"
        )

    # ── DEM availability check ─────────────────────────────────────────────
    if dem_path is None or not Path(dem_path).exists():
        return CatchmentResult(
            region_code=region_code, success=False,
            error=(
                "DEM not available for catchment delineation "
                f"(dem_path={dem_path}). "
                "Run Step 2 (DEM fetch) successfully before Step 9."
            )
        )

    dem_path = Path(dem_path)

    try:
        import math
        import numpy as np
        import rasterio.features
        from shapely.geometry import shape
        from shapely.ops import unary_union
        from backend.onboarding.stream_links import stream_link_catchments, DIRMAP_DEFAULT

        # ── Compatibility fixes for pysheds 0.5 on numpy>=2.5 / numba>=0.67 ───
        #  * numpy 2.5 removed np.in1d, which pysheds' accumulation still calls.
        #  * pysheds' fill_depressions() cannot compile under numba 0.67 (KeyError on a zip/count
        #    generator) and its catchment() segfaults natively.  Depressions are therefore filled
        #    with morphological reconstruction (scikit-image); catchments come from stream_links.py.
        if not hasattr(np, "in1d"):
            np.in1d = np.isin
        from skimage.morphology import reconstruction
        from pysheds.sview import Raster

        # ── Step 9.1-9.4: condition DEM, D8 flow direction, accumulation ──
        grid = Grid.from_raster(str(dem_path))
        dem = grid.read_raster(str(dem_path))
        a = np.asarray(dem, dtype=float)
        seed = a.copy()
        seed[1:-1, 1:-1] = np.nanmax(a)
        filled = reconstruction(seed, a, method="erosion")          # fill depressions (spill level)
        inflated = grid.resolve_flats(Raster(filled, viewfinder=dem.viewfinder))
        dirmap = DIRMAP_DEFAULT
        fdir = grid.flowdir(inflated, dirmap=dirmap)
        acc = grid.accumulation(fdir, dirmap=dirmap)

        with rasterio.open(str(dem_path)) as src:
            transform, crs = src.transform, src.crs
        lat0 = transform.f + transform.e * (a.shape[0] / 2)
        dx_m = abs(transform.a) * 111_320.0 * math.cos(math.radians(lat0))
        dy_m = abs(transform.e) * 110_574.0

        # ── Step 9.5-9.6: stream-link micro-catchments (see stream_links.py) ─
        res = stream_link_catchments(
            np.asarray(fdir), np.asarray(acc), filled, dx_m, dy_m,
            ACCUMULATION_THRESHOLD_CELLS, dirmap)
        labels = res["labels"]
        cell_km2 = dx_m * dy_m / 1e6
        area_km2 = res["cells"] * cell_km2
        keep = np.nonzero(area_km2 >= MIN_CATCHMENT_KM2)[0]
        dropped_small = len(area_km2) - len(keep)
        if len(keep) > MAX_CATCHMENTS:
            keep = keep[np.argsort(-area_km2[keep])[:MAX_CATCHMENTS]]
            warns.append(f"kept the {MAX_CATCHMENTS} largest of {len(area_km2)} stream-link catchments")
        if dropped_small:
            warns.append(f"{dropped_small} stream-link catchments below {MIN_CATCHMENT_KM2} km2 not written")
        warns.append("info: depressions filled by morphological reconstruction; catchments are "
                     "incremental stream-link sub-catchments (each cell to its first outlet downstream)")

        keep_ids = {int(res["ids"][k]): int(k) for k in keep}
        shapes = rasterio.features.shapes(
            labels, mask=np.isin(labels, list(keep_ids)), transform=transform, connectivity=8)
        parts: dict = {}
        for geom, val in shapes:
            parts.setdefault(int(val), []).append(shape(geom))

        rows = []
        for cid, k in sorted(keep_ids.items(), key=lambda kv: kv[0]):
            if cid not in parts:
                continue
            poly = unary_union(parts[cid]).simplify(abs(transform.a) / 2.0)
            if not poly.is_valid:
                poly = poly.buffer(0)                      # simplify can self-touch thin catchments
            r, c = res["outlet_rc"][k]
            lon_o = transform.c + (c + 0.5) * transform.a
            lat_o = transform.f + (r + 0.5) * transform.e
            rows.append({
                "catchment_id":      f"{region_code}_c{len(rows):04d}",
                "region_code":       region_code,
                "area_km2":          round(float(area_km2[k]), 4),
                # true longest D8 flow path to the outlet (replaces the earlier area/slope proxy)
                "upslope_reach_km":  round(float(res["flow_length_m"][k]) / 1000.0, 3),
                "flow_length_m":     round(float(res["flow_length_m"][k]), 1),
                "relief_m":          round(float(res["relief_m"][k]), 1),
                "channel_slope_m_m": round(float(res["channel_slope_m_m"][k]), 5),
                "mean_slope_deg":    round(float(res["mean_slope_deg"][k]), 2),
                "tc_min":            round(float(res["tc_min"][k]), 2),
                "outlet_hex_id":     h3.latlng_to_cell(lat_o, lon_o, 8),
                # Gap Analysis §0.2: provenance — REAL_VALIDATED for DEM-derived
                "provenance":        ProvenanceTag.REAL_VALIDATED.value,
                "geometry":          poly,
            })

        if not rows:
            return CatchmentResult(
                region_code=region_code, success=False,
                error=(
                    "No valid catchments delineated. The DEM may be too flat "
                    "or the accumulation threshold too high for this region. "
                    f"Try reducing ACCUMULATION_THRESHOLD_CELLS (currently "
                    f"{ACCUMULATION_THRESHOLD_CELLS})."
                ),
                warnings=warns,
            )

        # ── Step 9.7: Write 'catchments' layer to GeoPackage ──────────────
        gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs or "EPSG:4326")
        gdf.to_file(str(gpkg_path), driver="GPKG", layer="catchments")
        print(f"      Catchments: {len(rows)} written to {gpkg_path.name}")

        return CatchmentResult(
            region_code=region_code,
            success=True,
            catchment_count=len(rows),
            gpkg_path=gpkg_path,
            warnings=warns,
        )

    except Exception as e:
        return CatchmentResult(
            region_code=region_code, success=False,
            error=f"Catchment delineation error: {type(e).__name__}: {e}",
            warnings=warns,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_to_polygon(mask, transform):
    """
    Convert a boolean 2D numpy mask to a shapely polygon using rasterio.features.
    Returns the largest polygon if the mask is multi-part.
    """
    try:
        import rasterio.features
        import numpy as np
        from shapely.geometry import shape
        from shapely.ops import unary_union

        shapes = list(rasterio.features.shapes(
            mask.astype("uint8"),
            transform=transform,
        ))
        polys = [shape(s) for s, v in shapes if v == 1]
        if not polys:
            return None
        return max(polys, key=lambda p: p.area)
    except Exception:
        return None


def _polygon_area_km2(polygon) -> float:
    """
    Compute the area of a WGS84 shapely polygon in km².
    Uses a rough spherical approximation via the centroid latitude.
    For Phase 1 this is acceptable; replace with pyproj for higher precision.
    """
    import math
    centroid = polygon.centroid
    lat_rad  = math.radians(centroid.y)
    # Degrees to km conversion at this latitude
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(lat_rad)
    # Approximate: convert bounds to km and scale the polygon area
    bounds = polygon.bounds          # (minx, miny, maxx, maxy) in degrees
    lon_span = (bounds[2] - bounds[0]) * km_per_deg_lon
    lat_span = (bounds[3] - bounds[1]) * km_per_deg_lat
    # Bounding-box area × polygon fill ratio
    bbox_area_km2 = lon_span * lat_span
    bbox_deg_area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
    poly_deg_area = polygon.area
    fill_ratio    = poly_deg_area / bbox_deg_area if bbox_deg_area > 0 else 1.0
    return bbox_area_km2 * fill_ratio
