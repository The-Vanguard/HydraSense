"""
backend/onboarding/h3_grid.py
Step 5 of the Autonomous Region Onboarding Pipeline (Final.md §6, step 5 / §14.7).

Generates the H3 hexagonal grid for any resolved bounding box.

Resolution selection (Final.md §14.7 — automatic, not a config value):
  - Bbox area < 200 km²  → resolution 9 (~0.105 km² per hex)
  - Bbox area 200–2000 km² → resolution 8 (~0.737 km² per hex) [default]
  - Bbox area > 2000 km²   → resolution 7 (~5.16 km² per hex)

For each hex in the grid, the module also samples terrain and soil raster
values at the hex centroid, producing the per-hex static feature row that
goes into the GeoPackage and the risk engine.

h3-py v4 API is used throughout (latlng_to_cell, cell_to_latlng,
cell_to_boundary, grid_disk, get_resolution — Final.md §15.7 confirmed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import h3

# Gap Analysis §0.2 / Phase 0: provenance stamping on every hex feature row.
# provenance_for_source maps a source descriptor string to the canonical tag.
from backend.provenance import ProvenanceTag, provenance_for_source

# Resolution thresholds (km²)
RES_THRESHOLDS = [
    (200.0,   9),   # < 200 km²  → res 9
    (2000.0,  8),   # < 2000 km² → res 8
    (999999., 7),   # else        → res 7
]

# Earth radius (km) — for bbox area estimate
EARTH_RADIUS_KM = 6371.0


@dataclass
class H3GridResult:
    region_code: str
    resolution:  int
    hex_ids:     list[str] = field(default_factory=list)
    hex_count:   int = 0
    bbox:        dict = field(default_factory=dict)
    # Per-hex feature rows: {hex_id: {feature_name: value, ...}}
    hex_features: dict = field(default_factory=dict)


def _bbox_area_km2(bbox: dict) -> float:
    """Approximate bounding box area in km² using spherical geometry."""
    lat_span = abs(bbox["north"] - bbox["south"])
    lon_span = abs(bbox["east"]  - bbox["west"])
    mid_lat  = (bbox["north"] + bbox["south"]) / 2.0
    height_km = lat_span * 111.32
    width_km  = lon_span * 111.32 * math.cos(math.radians(mid_lat))
    return height_km * width_km


def select_resolution(bbox: dict) -> int:
    """
    Auto-select H3 resolution from bbox area (Final.md §14.7).
    Never read from config — always computed from actual extent.
    """
    area = _bbox_area_km2(bbox)
    for threshold, res in RES_THRESHOLDS:
        if area < threshold:
            return res
    return 7   # safety fallback for very large bbox


def _sample_raster_at_latlon(
    arr: Optional[np.ndarray],
    lat: float,
    lon: float,
    transform,
) -> Optional[float]:
    """
    Sample a raster array at a geographic coordinate using the affine transform.
    Returns None if out of bounds or NaN.
    """
    if arr is None or transform is None:
        return None
    # Convert lat/lon to pixel row/col
    col = (lon - transform.c) / transform.a
    row = (lat - transform.f) / transform.e
    r, c = int(round(row)), int(round(col))
    ny, nx = arr.shape
    if 0 <= r < ny and 0 <= c < nx:
        val = arr[r, c]
        return None if np.isnan(val) else float(val)
    return None


def build_h3_grid(
    region_code: str,
    bbox: dict,
    terrain_result=None,    # TerrainResult | None
    lulc_raster: Optional[np.ndarray] = None,
    lulc_transform=None,
    ndvi_raster: Optional[np.ndarray] = None,
    ndvi_transform=None,
    historical_event_count_by_hex: Optional[dict] = None,    # {hex_id: int}
    gsi_class_by_hex: Optional[dict] = None,                  # {hex_id: str}
    soil_params=None,        # SoilParams | None
) -> H3GridResult:
    """
    Main entry point. Generates H3 grid and samples all static features
    at each hex centroid.

    Returns H3GridResult with hex_features populated as:
    {
      hex_id: {
        "slope_deg": float, "aspect": float, "TWI": float, "TRI": float,
        "elevation": float, "distance_to_stream_m": float,
        "drainage_density": float, "flow_accumulation": float,
        "hand_m": float, "curve_number": float,
        "land_use_class": int, "ndvi_mean": float,
        "historical_event_count_500m": int,
        "gsi_susceptibility_class": str,
        "has_local_calibration": bool,
      }
    }
    """
    resolution = select_resolution(bbox)
    print(f"    H3 grid: {region_code} — resolution {resolution} (bbox ~{_bbox_area_km2(bbox):.0f} km²)")

    # Generate hex IDs covering the bbox
    # Use h3.geo_to_cells equivalent: polyfill a rectangular polygon
    # h3-py v4: h3.geo_to_cells(geojson_polygon, resolution)
    polygon_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [bbox["west"],  bbox["south"]],
            [bbox["east"],  bbox["south"]],
            [bbox["east"],  bbox["north"]],
            [bbox["west"],  bbox["north"]],
            [bbox["west"],  bbox["south"]],
        ]]
    }
    try:
        hex_set = h3.geo_to_cells(polygon_geojson, resolution)
    except Exception:
        # Fallback to manual grid scan
        hex_set = _manual_polyfill(bbox, resolution)

    hex_ids = sorted(hex_set)
    print(f"    H3 grid: {len(hex_ids)} hexes at resolution {resolution}")

    # Build per-hex feature rows
    terrain_transform  = terrain_result.transform  if terrain_result  else None
    terrain_arrays     = terrain_result.arrays     if terrain_result  else {}

    # Scalar drainage_density (one value per region, not per-cell)
    dd_arr = terrain_arrays.get("drainage_density")
    dd_scalar = float(np.nanmean(dd_arr)) if dd_arr is not None else 0.0

    has_cal = bool(gsi_class_by_hex)   # has_local_calibration = True if any GSI class available

    hex_features: dict = {}
    for hex_id in hex_ids:
        lat, lon = h3.cell_to_latlng(hex_id)

        def sample(key: str) -> Optional[float]:
            arr = terrain_arrays.get(key)
            return _sample_raster_at_latlon(arr, lat, lon, terrain_transform)

        lulc_val = _sample_raster_at_latlon(lulc_raster, lat, lon, lulc_transform)
        ndvi_val = _sample_raster_at_latlon(ndvi_raster, lat, lon, ndvi_transform)

        # Determine provenance for this hex's static features (Gap Analysis §0.2).
        # REAL_VALIDATED: DEM was fetched from a real source and terrain was computed.
        # SIMULATED:      no DEM was available; all terrain values will be None,
        #                 so this hex cannot be used in science paths.
        hex_provenance = (
            ProvenanceTag.REAL_VALIDATED.value
            if terrain_result is not None and terrain_result.success
            else ProvenanceTag.SIMULATED.value
        )

        hex_features[hex_id] = {
            # Terrain features
            "slope_deg":             sample("slope_deg"),
            "aspect":                sample("aspect"),
            "TWI":                   sample("TWI"),
            "TRI":                   sample("TRI"),
            "elevation":             sample("elevation"),
            "distance_to_stream_m":  sample("distance_to_stream_m"),
            "flow_accumulation":     sample("flow_accumulation"),
            "hand_m":                sample("hand_m"),
            "curve_number":          sample("curve_number"),
            # Drainage density is a per-region scalar
            "drainage_density":      dd_scalar,
            # Land cover / vegetation
            "land_use_class":        int(lulc_val) if lulc_val is not None else None,
            "ndvi_mean":             ndvi_val,
            # Historical context
            "historical_event_count_500m": (
                historical_event_count_by_hex.get(hex_id, 0)
                if historical_event_count_by_hex else 0
            ),
            "gsi_susceptibility_class": (
                gsi_class_by_hex.get(hex_id, "unknown")
                if gsi_class_by_hex else "unknown"
            ),
            # Calibration flag — the 29th feature (Final.md §10.3)
            "has_local_calibration": has_cal,
            # Gap Analysis §0.2 Phase 0: provenance tag on every feature row.
            # This is the source-of-truth for the CI leakage test and the
            # runtime assert_no_simulated_in_features() guard.
            "provenance":            hex_provenance,
        }

    return H3GridResult(
        region_code=region_code,
        resolution=resolution,
        hex_ids=hex_ids,
        hex_count=len(hex_ids),
        bbox=bbox,
        hex_features=hex_features,
    )


def _manual_polyfill(bbox: dict, resolution: int) -> set:
    """
    Fallback grid generation: scan lat/lon grid and collect unique H3 cells.
    Used if h3.geo_to_cells is unavailable (v3→v4 API mismatch).
    """
    step = {7: 0.05, 8: 0.02, 9: 0.008}.get(resolution, 0.02)
    hexes = set()
    lat = bbox["south"]
    while lat <= bbox["north"]:
        lon = bbox["west"]
        while lon <= bbox["east"]:
            hexes.add(h3.latlng_to_cell(lat, lon, resolution))
            lon += step
        lat += step
    return hexes
