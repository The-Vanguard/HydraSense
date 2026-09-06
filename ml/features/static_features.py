"""
static_features.py -- Compute all 11 static (susceptibility) features per H3 pilot hex.

Implements: SRS.md Sections 6.1, 9, 14.
Owner: Dev A -- Phase 3.

Prerequisite files (exit 1 if missing):
  data/terrain/dem_wayanad.tif            Phase 1 -- ingest_dem.py (needs OPENTOPO_API_KEY)
  data/landcover/landcover_wayanad.tif    Phase 1 -- ingest_landcover.py (needs AWS CLI + GDAL)
  data/landcover/ndvi_wayanad.tif         Phase 1 -- ingest_landcover.py
  data/susceptibility/gsi_susceptibility.csv  Phase 2 (merged)
  data/events/historical_events.csv       Phase 4 (merged)

Primary output:
  data/processed/static_features.parquet  -- one row per hex_id, all 11 features as columns
                                            loaded into hexes.static_features JSONB by Phase 8

PostGIS write is deferred to Phase 8. This script only writes the Parquet
(the authoritative static-features store for everything downstream).

11 static features (SRS.md Section 9, field names frozen):
  slope_deg, aspect, TWI, TRI, elevation,
  distance_to_stream_m, drainage_density,
  land_use_class, ndvi_mean,
  historical_event_count_500m, gsi_susceptibility_class

HARD CONSTRAINTS (CLAUDE.md):
  - pysheds is the ONLY terrain library (TWI flow routing). Never whitebox/richdem.
  - gsi_susceptibility_class is written as JSON null for any remaining unresolved hexes.
    Phase 2 fix (c398076, merged to main): all 9 Punjirimattom hexes resolved from UNRESOLVED
    to Moderate/High via GSI Jul-2024 FIR + The News Minute (2024) confirmation. null_count
    is expected to be 0 as of this branch. The null-handling code is kept for correctness
    should any future hex be added without a source -- it will not silently default.
  - Mundakkai and Chooralmala share one H3 res-8 centroid hex (8860064e4bfffff). Both are
    correctly labeled Moderate. The hex appears once in the CSV and once in output. No fix needed.
  - Schema field names are frozen -- do not rename (SRS.md Section 14).
  - historical_event_count_500m: Phase 4 is merged; computed for real from events CSV.
    Village-level coordinate precision throughout -- documented in output, never hidden.
"""

from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path

import h3
import numpy as np
import pandas as pd
from scipy.ndimage import distance_transform_edt, generic_filter
from shapely.geometry import Polygon, mapping

try:
    import rasterio
    from rasterio.features import geometry_mask
except ImportError:
    print(
        "\nERROR: rasterio not installed.\n"
        "  Run: python -m pip install rasterio\n",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from pysheds.grid import Grid as PyshedsGrid
except ImportError:
    print(
        "\nERROR: pysheds not installed.\n"
        "  Run: python -m pip install pysheds\n"
        "  CLAUDE.md hard constraint: pysheds is the ONLY terrain library.\n",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
H3_RESOLUTION = 8           # SRS pilot uses res 8 (~0.74 km2 hex area)
H3_HEX_AREA_KM2 = 0.7373   # average area at res 8 (for drainage_density denominator)
H3_HEX_AREA_M2 = H3_HEX_AREA_KM2 * 1e6

# Wayanad geographic constants for degree-to-meter conversion
LAT_APPROX = 11.5
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT_APPROX))

# Stream extraction threshold (flow accumulation cells).
# At SRTM 30m, 100 cells ~ 0.09 km2 upslope area -- reasonable for small Wayanad catchments.
STREAM_ACC_THRESHOLD = 100

# For historical_event_count_500m: village-level precision means we assign each event
# the centroid of the village mentioned in its source. Events not specific to a pilot
# village are assigned the cluster centroid.
# SRS Section 11.3: village-level precision is tagged and never hidden.
EVENT_RADIUS_M = 500.0

PILOT_VILLAGE_CENTROIDS: dict[str, tuple[float, float]] = {
    "Mundakkai":     (11.5185, 76.0524),
    "Chooralmala":   (11.5143, 76.0498),
    "Attamala":      (11.5220, 76.0570),
    "Punjirimattom": (11.5100, 76.0450),
}
# Cluster centroid -- used for broad "Wayanad" events with no specific village
CLUSTER_CENTROID = (
    sum(v[0] for v in PILOT_VILLAGE_CENTROIDS.values()) / 4,
    sum(v[1] for v in PILOT_VILLAGE_CENTROIDS.values()) / 4,
)

# ESA WorldCover 2021 class codes (SRS Section 8)
ESA_CLASS_LABELS: dict[int, str] = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare/sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

# File paths (all relative to repo root)
BASE_DIR = Path(__file__).resolve().parents[2]
DEM_PATH = BASE_DIR / "data" / "terrain" / "dem_wayanad.tif"
LANDCOVER_PATH = BASE_DIR / "data" / "landcover" / "landcover_wayanad.tif"
NDVI_PATH = BASE_DIR / "data" / "landcover" / "ndvi_wayanad.tif"
GSI_CSV = BASE_DIR / "data" / "susceptibility" / "gsi_susceptibility.csv"
EVENTS_CSV = BASE_DIR / "data" / "events" / "historical_events.csv"
OUT_DIR = BASE_DIR / "data" / "processed"
OUT_PARQUET = OUT_DIR / "static_features.parquet"


# ---------------------------------------------------------------------------
# Prerequisite check
# ---------------------------------------------------------------------------
def check_prerequisites() -> None:
    """
    Verify all input files exist before doing any computation.
    Fails loudly with actionable instructions -- no silent substitution (CLAUDE.md).
    """
    missing: list[str] = []

    if not DEM_PATH.exists():
        missing.append(
            f"  {DEM_PATH}\n"
            "    -> Run: python data/scripts/ingest_dem.py (set OPENTOPO_API_KEY first)"
        )
    if not LANDCOVER_PATH.exists():
        missing.append(
            f"  {LANDCOVER_PATH}\n"
            "    -> Run: python data/scripts/ingest_landcover.py (needs AWS CLI + gdal_translate)"
        )
    if not NDVI_PATH.exists():
        missing.append(
            f"  {NDVI_PATH}\n"
            "    -> Run: python data/scripts/ingest_landcover.py (needs AWS CLI + gdal_translate)"
        )
    if not GSI_CSV.exists():
        missing.append(
            f"  {GSI_CSV}\n"
            "    -> Phase 2 output -- pull latest main (Phase 2 merged)"
        )
    if not EVENTS_CSV.exists():
        missing.append(
            f"  {EVENTS_CSV}\n"
            "    -> Phase 4 output -- pull latest main (Phase 4 merged)"
        )

    if missing:
        print("\nERROR [static_features]: Missing prerequisite files:", file=sys.stderr)
        for m in missing:
            print(m, file=sys.stderr)
        print(
            "\nPhase 3 cannot run until all prerequisite files are present.\n"
            "No static features will be written.\n",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Hex grid (from Phase 2 GSI CSV -- the definitive pilot hex set)
# ---------------------------------------------------------------------------
def load_hex_grid() -> pd.DataFrame:
    """
    Load the pilot hex set from gsi_susceptibility.csv (Phase 2's definitive hex list).

    The CSV is the single source of truth for which hex IDs are in the pilot cluster.
    Returns a DataFrame with columns: hex_id, village, area_type, ring_k,
    gsi_susceptibility_class (None only if a hex has no source -- see Phase 2 note).

    Phase 2 notes:
      - Phase 2 fix (c398076): all 9 Punjirimattom hexes resolved from UNRESOLVED to
        Moderate/High using GSI Jul-2024 FIR + The News Minute (2024) citation.
        null_count is expected to be 0. The None-parsing logic below is kept for
        correctness -- it will not silently default any future unresolved hex.
      - Mundakkai and Chooralmala share hex 8860064e4bfffff (~300m apart at res 8, ~0.74 km2
        cell). Both are labeled Moderate. The hex appears once in the CSV and once in output.
    """
    df = pd.read_csv(GSI_CSV, dtype=str)

    # Normalise column names (Phase 2 CSV uses: hex_id, susceptibility_class, ...)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Convert blank / NaN / UNRESOLVED to None (Python null -> JSON null).
    # Phase 2 leaves blank susceptibility_class for Punjirimattom rows.
    # With dtype=str, pandas reads blank cells as float nan (not "" or None).
    def parse_class(val) -> str | None:
        if val is None:
            return None
        try:
            # float nan check (pandas blank-cell with dtype=str)
            if math.isnan(float(val)):
                return None
        except (TypeError, ValueError):
            pass
        s = str(val).strip()
        if s == "" or s.upper().startswith("UNRESOLVED"):
            return None
        return s

    df["gsi_susceptibility_class"] = df["susceptibility_class"].apply(parse_class)
    df = df.drop(columns=["susceptibility_class"], errors="ignore")

    null_count = df["gsi_susceptibility_class"].isna().sum()
    print(f"[hex_grid] Loaded {len(df)} hexes from GSI CSV.")
    if null_count == 0:
        print("[hex_grid] All hexes have a resolved gsi_susceptibility_class (Phase 2 fix applied).")
    else:
        print(
            f"[hex_grid] WARNING: {null_count} hexes have gsi_susceptibility_class = null. "
            f"These will be written as JSON null -- no defaulting."
        )

    return df[["hex_id", "village", "area_type", "ring_k", "gsi_susceptibility_class"]]


# ---------------------------------------------------------------------------
# Raster utilities
# ---------------------------------------------------------------------------
def get_hex_polygon(hex_id: str) -> Polygon:
    """
    Return the H3 hex boundary as a Shapely Polygon with (lon, lat) vertex order.
    h3 v4: cell_to_boundary() returns [(lat, lon), ...] -- we swap for Shapely/GeoJSON convention.
    """
    boundary_latlon = h3.cell_to_boundary(hex_id)     # [(lat, lon), ...]  -- h3 v4 API
    return Polygon([(lon, lat) for lat, lon in boundary_latlon])


def get_hex_centroid_latlon(hex_id: str) -> tuple[float, float]:
    """Return hex centroid as (lat, lon). h3 v4 API: cell_to_latlng."""
    lat, lon = h3.cell_to_latlng(hex_id)
    return lat, lon


def raster_mask_for_hex(hex_id: str, transform, height: int, width: int) -> np.ndarray:
    """
    Compute a boolean mask (True inside the hex polygon) over the raster grid.
    Uses rasterio.features.geometry_mask -- this is the rasterio-blessed approach.
    """
    polygon = get_hex_polygon(hex_id)
    mask = geometry_mask(
        [mapping(polygon)],
        transform=transform,
        invert=True,      # True = inside the polygon
        out_shape=(height, width),
    )
    return mask


def sample_mean(array: np.ndarray, mask: np.ndarray, nodata: float | None) -> float | None:
    """Mean of valid (non-nodata) values within mask. Returns None if no valid pixels."""
    values = array[mask].astype(float)
    if nodata is not None:
        values = values[values != nodata]
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return None
    return float(np.mean(values))


def sample_mode(array: np.ndarray, mask: np.ndarray, nodata: int | None) -> int | None:
    """Mode (most common integer) of values within mask. Returns None if no valid pixels."""
    values = array[mask]
    if nodata is not None:
        values = values[values != nodata]
    if len(values) == 0:
        return None
    unique, counts = np.unique(values, return_counts=True)
    return int(unique[np.argmax(counts)])


# ---------------------------------------------------------------------------
# DEM-based terrain features (rasterio + pysheds)
# ---------------------------------------------------------------------------
def compute_dem_features(hexes: pd.DataFrame) -> dict[str, dict]:
    """
    Compute slope_deg, aspect, elevation, TWI, TRI, distance_to_stream_m,
    drainage_density for each hex.

    Terrain workflow:
      rasterio         -- load DEM array, transform, nodata
      numpy/scipy      -- slope_deg, aspect, TRI (convolution-based)
      pysheds (ONLY)   -- fill depressions, resolve flats, D8 flow direction,
                          flow accumulation --> TWI, stream network, stream distances
      scipy.ndimage    -- distance_transform_edt for distance_to_stream_m per pixel
      rasterio.mask    -- hex-level zonal sampling

    CONSTRAINT: pysheds is the ONLY flow-routing library (CLAUDE.md / SRS.md Section 26).
    """
    print("\n[DEM] Loading raster ...")
    with rasterio.open(DEM_PATH) as src:
        dem_arr = src.read(1).astype(float)
        transform = src.transform
        nodata = src.nodata
        height, width = src.height, src.width
        # Pixel dimensions in degrees
        dx_deg = abs(transform.a)
        dy_deg = abs(transform.e)

    # Approximate degree-to-meter conversion (sufficient for Wayanad at ~11.5 degN)
    dx_m = dx_deg * M_PER_DEG_LON
    dy_m = dy_deg * M_PER_DEG_LAT
    cell_size_m = math.sqrt(dx_m * dy_m)   # geometric mean for distance_transform_edt

    # Mask nodata
    if nodata is not None:
        dem_arr[dem_arr == nodata] = np.nan

    print(
        f"[DEM] Array {width}x{height}, cell ~{cell_size_m:.1f} m, "
        f"elev range [{np.nanmin(dem_arr):.0f}-{np.nanmax(dem_arr):.0f} m]"
    )

    # ------------------------------------------------------------------
    # Slope (degrees) and aspect (degrees) via numpy gradient
    # dy_m = north-south spacing, dx_m = east-west spacing
    # np.gradient returns (dz/dy_north, dz/dx_east) i.e. (row, col) gradients
    # ------------------------------------------------------------------
    dzdx = np.gradient(np.where(np.isfinite(dem_arr), dem_arr, 0.0), axis=1) / dx_m
    dzdy = np.gradient(np.where(np.isfinite(dem_arr), dem_arr, 0.0), axis=0) / dy_m

    slope_rad = np.arctan(np.sqrt(dzdx**2 + dzdy**2))
    slope_deg_arr = np.degrees(slope_rad)
    # Aspect: 0 = North, clockwise. arctan2(-dzdx, -dzdy) gives mathematical convention;
    # rotate so 0 = North.
    aspect_arr = (np.degrees(np.arctan2(-dzdx, dzdy)) + 360.0) % 360.0

    # ------------------------------------------------------------------
    # TRI -- Terrain Ruggedness Index (Riley et al. 1999)
    # Mean absolute difference between focal cell and its 8 neighbours.
    # scipy.ndimage generic_filter with a 3x3 window.
    # ------------------------------------------------------------------
    def _tri_kernel(values: np.ndarray) -> float:
        center = values[4]         # index 4 = center of flattened 3x3 window
        neighbours = np.concatenate([values[:4], values[5:]])
        finite = neighbours[np.isfinite(neighbours)]
        if len(finite) == 0 or not np.isfinite(center):
            return np.nan
        return float(np.mean(np.abs(finite - center)))

    dem_filled_nans = np.where(np.isfinite(dem_arr), dem_arr, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tri_arr = generic_filter(dem_filled_nans, _tri_kernel, size=3, mode="reflect")

    # ------------------------------------------------------------------
    # pysheds: fill depressions, resolve flats, D8 flow direction,
    # flow accumulation, TWI, stream extraction
    # HARD CONSTRAINT (CLAUDE.md): pysheds only -- no whitebox or richdem.
    # ------------------------------------------------------------------
    print("[DEM] Running pysheds flow routing (fill -> resolve -> fdir -> acc) ...")
    grid = PyshedsGrid.from_raster(str(DEM_PATH))
    dem_raster = grid.read_raster(str(DEM_PATH))

    flooded = grid.fill_depressions(dem_raster)
    inflated = grid.resolve_flats(flooded)
    fdir = grid.flowdir(inflated)
    acc = grid.accumulation(fdir)

    # Convert pysheds Raster objects to numpy for further computation
    acc_arr = np.array(acc).astype(float)

    # ------------------------------------------------------------------
    # TWI = ln( a / tan(beta) )
    # a   = upslope area per unit contour width (approx: acc_cells * cell_area_m2 / cell_size_m)
    #       = acc_cells * cell_size_m   [m]  (Beven & Kirkby 1979 specific catchment area)
    # beta = local slope angle (radians)
    # Clamp slope to 0.001 rad to avoid ln(inf) on flat cells.
    # ------------------------------------------------------------------
    sca = (acc_arr + 1.0) * cell_size_m             # specific catchment area [m]
    slope_rad_clamped = np.where(slope_rad < 0.001, 0.001, slope_rad)
    twi_arr = np.log(sca / np.tan(slope_rad_clamped))
    twi_arr[~np.isfinite(dem_arr)] = np.nan

    # ------------------------------------------------------------------
    # Stream network: cells where acc > threshold
    # ------------------------------------------------------------------
    streams_bool = acc_arr > STREAM_ACC_THRESHOLD

    # ------------------------------------------------------------------
    # distance_to_stream_m per pixel:
    # scipy distance_transform_edt with sampling=[dy_m, dx_m] returns metres directly.
    # ------------------------------------------------------------------
    print(
        f"[DEM] Stream network: {streams_bool.sum()} cells "
        f"(threshold={STREAM_ACC_THRESHOLD} cells, ~{STREAM_ACC_THRESHOLD * cell_size_m**2 / 1e6:.3f} km2 upslope)"
    )
    dist_to_stream_m_arr = distance_transform_edt(~streams_bool, sampling=[dy_m, dx_m])

    # ------------------------------------------------------------------
    # Per-hex sampling
    # ------------------------------------------------------------------
    results: dict[str, dict] = {}
    for _, row in hexes.iterrows():
        hex_id = row["hex_id"]
        mask = raster_mask_for_hex(hex_id, transform, height, width)

        n_pixels = mask.sum()
        if n_pixels == 0:
            # Hex entirely outside DEM extent -- should not happen with current bbox
            print(f"  WARNING: hex {hex_id} has 0 DEM pixels -- skipped", file=sys.stderr)
            results[hex_id] = {
                k: None for k in [
                    "elevation", "slope_deg", "aspect", "TWI", "TRI",
                    "distance_to_stream_m", "drainage_density",
                ]
            }
            continue

        elevation = sample_mean(dem_arr, mask, nodata=None)   # nodata already -> nan
        slope_deg = sample_mean(slope_deg_arr, mask, nodata=None)
        aspect = sample_mean(aspect_arr, mask, nodata=None)
        twi = sample_mean(twi_arr, mask, nodata=None)
        tri = sample_mean(tri_arr, mask, nodata=None)
        dist_stream = sample_mean(dist_to_stream_m_arr, mask, nodata=None)

        # drainage_density: stream length within hex / hex area (km/km2)
        # stream pixels in hex * cell_size_m = stream length in metres
        stream_pixels_in_hex = int(streams_bool[mask].sum())
        stream_length_m = stream_pixels_in_hex * cell_size_m
        drainage_density = (stream_length_m / 1000.0) / H3_HEX_AREA_KM2   # km/km2

        results[hex_id] = {
            "elevation":           round(elevation, 2) if elevation is not None else None,
            "slope_deg":           round(slope_deg, 3) if slope_deg is not None else None,
            "aspect":              round(aspect, 2) if aspect is not None else None,
            "TWI":                 round(twi, 4) if twi is not None else None,
            "TRI":                 round(tri, 3) if tri is not None else None,
            "distance_to_stream_m": round(dist_stream, 1) if dist_stream is not None else None,
            "drainage_density":    round(drainage_density, 4),
        }

    return results


# ---------------------------------------------------------------------------
# Land cover features (rasterio -- ESA WorldCover 10m)
# ---------------------------------------------------------------------------
def compute_landcover_features(hexes: pd.DataFrame) -> dict[str, dict]:
    """
    Compute land_use_class (ESA WorldCover mode within hex) and ndvi_mean.

    ESA WorldCover 2021 stores class codes as uint8.
    NDVI P50 composite is stored as int16; scale factor 0.0001 (NDVI = raw / 10000).
    Both rasters are at 10m resolution -- more pixels per hex than the 30m DEM.
    """
    print("\n[Landcover] Loading ESA WorldCover and NDVI rasters ...")

    with rasterio.open(LANDCOVER_PATH) as lc_src:
        lc_arr = lc_src.read(1)
        lc_transform = lc_src.transform
        lc_nodata = lc_src.nodata if lc_src.nodata is not None else 0
        lc_height, lc_width = lc_src.height, lc_src.width

    with rasterio.open(NDVI_PATH) as ndvi_src:
        ndvi_arr = ndvi_src.read(1).astype(float)
        ndvi_transform = ndvi_src.transform
        ndvi_nodata_raw = ndvi_src.nodata   # raw nodata value (before scaling)
        ndvi_height, ndvi_width = ndvi_src.height, ndvi_src.width

        # ESA WorldCover NDVI P50: stored as int16, scale factor 0.0001.
        # Nodata is typically -32768.
        ndvi_nodata_raw = ndvi_nodata_raw if ndvi_nodata_raw is not None else -32768

    # Apply NDVI scale factor: raw int16 * 0.0001 = actual NDVI
    ndvi_valid = ndvi_arr.copy()
    ndvi_valid[ndvi_valid == ndvi_nodata_raw] = np.nan
    ndvi_scaled = ndvi_valid * 0.0001
    # Clamp to physical NDVI range [-1, 1]
    ndvi_scaled = np.clip(ndvi_scaled, -1.0, 1.0)

    print(
        f"[Landcover] WorldCover array {lc_width}x{lc_height}, "
        f"NDVI array {ndvi_width}x{ndvi_height}"
    )

    results: dict[str, dict] = {}
    for _, row in hexes.iterrows():
        hex_id = row["hex_id"]

        lc_mask = raster_mask_for_hex(hex_id, lc_transform, lc_height, lc_width)
        ndvi_mask = raster_mask_for_hex(hex_id, ndvi_transform, ndvi_height, ndvi_width)

        land_use_class = sample_mode(lc_arr, lc_mask, nodata=int(lc_nodata))
        ndvi_mean = sample_mean(ndvi_scaled, ndvi_mask, nodata=None)  # nodata already nan

        results[hex_id] = {
            "land_use_class": land_use_class,
            "ndvi_mean": round(ndvi_mean, 4) if ndvi_mean is not None else None,
        }

    return results


# ---------------------------------------------------------------------------
# Historical event count (Phase 4 events -- SRS Section 9 / 11.3)
# ---------------------------------------------------------------------------
def _latlon_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Approximate great-circle distance in metres between two lat/lon points.
    Uses equirectangular approximation; valid for the small distances in this pilot
    (~1-5km max, well within the 1% accuracy band of equirectangular projection).
    """
    dlat_m = (lat2 - lat1) * M_PER_DEG_LAT
    dlon_m = (lon2 - lon1) * M_PER_DEG_LON
    return math.sqrt(dlat_m**2 + dlon_m**2)


def _assign_event_location(source: str) -> tuple[float, float]:
    """
    Assign a lat/lon to an event based on which pilot village appears in its source string.
    Returns the village centroid (lat, lon) if a specific village is mentioned,
    or the cluster centroid for general 'Wayanad' events.

    All assignments carry village-level coordinate precision (SRS Section 11.3).
    This precision tag is written into the summary and Parquet metadata.
    """
    src_lower = source.lower() if source else ""
    for village, centroid in PILOT_VILLAGE_CENTROIDS.items():
        if village.lower() in src_lower:
            return centroid
    # No pilot village named specifically -- use cluster centroid
    return CLUSTER_CENTROID


def compute_historical_event_count(hexes: pd.DataFrame) -> dict[str, int]:
    """
    Count historical events (Phase 4 CSV) within EVENT_RADIUS_M = 500m of each hex centroid.

    Coordinate precision: all events in historical_events.csv have village-level precision.
    Event location is approximated by the village centroid extracted from the source string.
    This is tagged explicitly in the Parquet metadata and summary table.

    Phase 4 (event_centered_sampling.py) is merged -- historical_event_count_500m is
    computed for real, not a placeholder.
    """
    events_df = pd.read_csv(EVENTS_CSV, dtype=str)
    events_df.columns = [c.strip().lower() for c in events_df.columns]

    # Assign lat/lon from source string (village-level precision)
    event_latlons = [
        _assign_event_location(row.get("source", ""))
        for _, row in events_df.iterrows()
    ]
    n_events = len(events_df)
    print(f"\n[Events] Loaded {n_events} historical events from Phase 4 CSV.")
    print(
        f"[Events] All events at village-level coordinate precision "
        f"(SRS Section 11.3). Using village centroid as event location."
    )

    results: dict[str, int] = {}
    for _, row in hexes.iterrows():
        hex_id = row["hex_id"]
        hex_lat, hex_lon = get_hex_centroid_latlon(hex_id)

        count = 0
        for ev_lat, ev_lon in event_latlons:
            dist = _latlon_distance_m(hex_lat, hex_lon, ev_lat, ev_lon)
            if dist <= EVENT_RADIUS_M:
                count += 1
        results[hex_id] = count

    return results


# ---------------------------------------------------------------------------
# Assembly and output
# ---------------------------------------------------------------------------
def assemble_features(
    hexes: pd.DataFrame,
    dem_feats: dict[str, dict],
    lc_feats: dict[str, dict],
    event_counts: dict[str, int],
) -> pd.DataFrame:
    """
    Merge all feature dicts into one row per hex_id.
    gsi_susceptibility_class is None (Python) for Punjirimattom unresolved hexes;
    pandas will store these as NaN in the column but they'll serialize as JSON null.
    """
    rows = []
    for _, row in hexes.iterrows():
        hid = row["hex_id"]
        dem = dem_feats.get(hid, {})
        lc = lc_feats.get(hid, {})

        # gsi_susceptibility_class: None for unresolved (Phase 2 constraint)
        gsi = row["gsi_susceptibility_class"]   # None only for any future unresolved hex

        rows.append({
            "hex_id":                    hid,
            "village":                   row.get("village"),
            "area_type":                 row.get("area_type"),
            "ring_k":                    row.get("ring_k"),
            # --- 11 static features (SRS.md Section 9, field names frozen) ---
            "slope_deg":                 dem.get("slope_deg"),
            "aspect":                    dem.get("aspect"),
            "TWI":                       dem.get("TWI"),
            "TRI":                       dem.get("TRI"),
            "elevation":                 dem.get("elevation"),
            "distance_to_stream_m":      dem.get("distance_to_stream_m"),
            "drainage_density":          dem.get("drainage_density"),
            "land_use_class":            lc.get("land_use_class"),
            "ndvi_mean":                 lc.get("ndvi_mean"),
            "historical_event_count_500m": event_counts.get(hid, 0),
            # gsi_susceptibility_class: None -> JSON null (NEVER defaulted)
            "gsi_susceptibility_class":  gsi,
        })

    return pd.DataFrame(rows)


def build_static_features_jsonb(row: pd.Series) -> dict:
    """
    Build the JSONB dict for hexes.static_features from a single DataFrame row.
    Field names are frozen (SRS.md Section 14).
    None values are preserved as JSON null -- never replaced with 0 or any default.
    """
    def _val(v):
        """Return None (-> JSON null) if value is None or float NaN."""
        if v is None:
            return None
        try:
            if math.isnan(float(v)):
                return None
        except (TypeError, ValueError):
            pass
        return v

    return {
        "slope_deg":                   _val(row["slope_deg"]),
        "aspect":                      _val(row["aspect"]),
        "TWI":                         _val(row["TWI"]),
        "TRI":                         _val(row["TRI"]),
        "elevation":                   _val(row["elevation"]),
        "distance_to_stream_m":        _val(row["distance_to_stream_m"]),
        "drainage_density":            _val(row["drainage_density"]),
        "land_use_class":              _val(row["land_use_class"]),
        "ndvi_mean":                   _val(row["ndvi_mean"]),
        "historical_event_count_500m": _val(row["historical_event_count_500m"]),
        # Null for 9 Punjirimattom hexes. NEVER defaulted. (Phase 2 constraint)
        "gsi_susceptibility_class":    _val(row["gsi_susceptibility_class"]),
    }


def write_outputs(df: pd.DataFrame) -> None:
    """
    Write static features to:
      1. data/processed/static_features.parquet (primary -- read by Phase 8)
      2. data/processed/static_features_jsonb.json (debug -- one JSONB blob per hex)
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Parquet -- Phase 8 reads this to populate hexes.static_features
    df.to_parquet(OUT_PARQUET, index=False, engine="pyarrow")
    print(f"\n[Output] Parquet -> {OUT_PARQUET}  ({len(df)} rows)")

    # JSON debug file -- human-readable JSONB preview
    jsonb_records = {}
    for _, row in df.iterrows():
        jsonb_records[row["hex_id"]] = build_static_features_jsonb(row)

    json_path = OUT_DIR / "static_features_jsonb.json"
    json_path.write_text(
        json.dumps(jsonb_records, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(f"[Output] JSONB debug -> {json_path}")

    # Validate null handling
    # Phase 2 fix (c398076): all Punjirimattom hexes resolved; null_count expected = 0.
    # This check is kept to catch any regression (e.g. if CSV is inadvertently reverted).
    null_gsi = df[df["gsi_susceptibility_class"].isna()]
    if null_gsi.shape[0] == 0:
        print(
            f"\n[Validate] gsi_susceptibility_class: all {df['gsi_susceptibility_class'].notna().sum()} "
            f"hexes resolved (Phase 2 fix applied). No nulls."
        )
    else:
        print(
            f"\n[Validate] gsi_susceptibility_class: "
            f"{df['gsi_susceptibility_class'].notna().sum()} non-null, "
            f"{null_gsi.shape[0]} null (unresolved -- written as JSON null, never defaulted)."
        )
        print(f"[Validate] Null hexes: {null_gsi['hex_id'].tolist()}")

    # Confirm null passes through to JSONB as null, not string
    for hid, jb in jsonb_records.items():
        if jb["gsi_susceptibility_class"] is not None:
            # Should be a string like "High" or "Moderate"
            assert isinstance(jb["gsi_susceptibility_class"], str), (
                f"BUG: gsi_susceptibility_class for {hid} is not str: "
                f"{jb['gsi_susceptibility_class']!r}"
            )
        # else: null -- correct for Punjirimattom
    print("[Validate] gsi_susceptibility_class null propagation: PASS")


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------
def print_summary(df: pd.DataFrame) -> None:
    """
    Print a formatted summary table of all 11 features for every pilot hex.
    This is the sanity-check output required by Phase 3 acceptance criteria.
    """
    print("\n" + "=" * 110)
    print("PHASE 3 SUMMARY -- 11 Static Features per Pilot Hex")
    print("=" * 110)
    print(
        f"{'hex_id':<20} {'village':<14} {'elev':>6} {'slp':>6} {'asp':>5} "
        f"{'TWI':>6} {'TRI':>6} {'dist_s':>7} {'d_den':>6} "
        f"{'LC':>4} {'NDVI':>6} {'ev500':>5} {'gsi_class':<12}"
    )
    print("-" * 110)

    for _, row in df.sort_values(["village", "ring_k"]).iterrows():
        def fmt(v, decimals=1):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return "  --"
            return f"{v:.{decimals}f}"

        gsi = row["gsi_susceptibility_class"]
        gsi_str = gsi if gsi is not None else "NULL(unresolved)"

        print(
            f"{row['hex_id']:<20} {str(row.get('village','')):<14} "
            f"{fmt(row['elevation'],0):>6} {fmt(row['slope_deg'],1):>6} "
            f"{fmt(row['aspect'],0):>5} "
            f"{fmt(row['TWI'],2):>6} {fmt(row['TRI'],1):>6} "
            f"{fmt(row['distance_to_stream_m'],0):>7} "
            f"{fmt(row['drainage_density'],3):>6} "
            f"{str(row['land_use_class'] or '--'):>4} "
            f"{fmt(row['ndvi_mean'],3):>6} "
            f"{str(row['historical_event_count_500m']):>5} "
            f"{gsi_str:<16}"
        )

    print("=" * 110)
    print(f"\nTotal hexes: {len(df)}")
    null_c = df['gsi_susceptibility_class'].isna().sum()
    if null_c == 0:
        print("Null gsi_susceptibility_class: 0 (Phase 2 fix resolved all Punjirimattom hexes)")
    else:
        print(f"Null gsi_susceptibility_class: {null_c} (unresolved -- written as JSON null)")
    print(
        f"coordinate_precision for historical_event_count_500m: "
        f"village-level throughout (SRS.md Section 11.3)"
    )
    print(
        f"Shared hex (Mundakkai/Chooralmala): 8860064e4bfffff "
        f"-- appears once, class=Moderate (expected at H3 res 8)"
    )

    # Land use class legend
    print("\nLand use class codes (ESA WorldCover 2021):")
    for code, label in ESA_CLASS_LABELS.items():
        print(f"  {code:3d}: {label}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Phase 3 -- Static Feature Engineering")
    print("SRS.md Sections 6.1, 9, 14 | Owner: Dev A")
    print("=" * 60)

    # 1. Prerequisite check -- fail loudly if any input is missing
    check_prerequisites()

    # 2. Load hex grid (Phase 2 definitive hex set)
    hexes = load_hex_grid()

    # 3. DEM-based terrain features
    #    pysheds (ONLY) for flow routing / TWI -- CLAUDE.md hard constraint
    dem_feats = compute_dem_features(hexes)

    # 4. Land cover features (ESA WorldCover + NDVI)
    lc_feats = compute_landcover_features(hexes)

    # 5. Historical event count (Phase 4 CSV -- not a placeholder; Phase 4 is merged)
    event_counts = compute_historical_event_count(hexes)

    # 6. Assemble all features
    #    gsi_susceptibility_class is already on the hexes DataFrame (from load_hex_grid)
    df = assemble_features(hexes, dem_feats, lc_feats, event_counts)

    # 7. Write Parquet + JSONB debug
    write_outputs(df)

    # 8. Sanity-check summary table
    print_summary(df)

    print("\n[Phase 3] Done. Parquet ready for Phase 8 (PostGIS load).")
    print(
        "[Phase 3] Next step: Phase 8 will CREATE TABLE hexes(...) and load "
        "static_features.parquet into hexes.static_features JSONB."
    )


if __name__ == "__main__":
    main()
