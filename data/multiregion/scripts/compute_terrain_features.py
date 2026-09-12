"""
compute_terrain_features.py -- Real point-sampled terrain features for the
multi-region flash-flood dataset (Wayanad + Idukki, tonight's scope).

Reuses the exact computational approach of ml/features/static_features.py
(rasterio for zonal/point sampling, pysheds -- the ONLY terrain library per
CLAUDE.md -- for flow routing) WITHOUT modifying that file, since it is a
Phase 3 file outside this session's scope. Adapted here to sample terrain
at named POINTS (villages / confirmed event locations) rather than an H3
hex grid, since the multi-region event set is point-centered, not
hex-gridded.

Flash-flood feature set (per the task's target schema -- new vs. the
Wayanad landslide pipeline, which never needed these):
  elevation, slope_deg, aspect, TWI, TRI,
  distance_to_river_m, flow_accumulation_cells, drainage_density_km_per_km2

HARD CONSTRAINT (CLAUDE.md): pysheds is the ONLY terrain library. No
synthetic/interpolated values where a real DEM pixel is missing -- null.
"""

import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np

# COMPAT SHIM: numpy 2.x removed np.in1d (deprecated alias for np.isin);
# pysheds 0.5's internal _d8_accumulation() still calls np.in1d directly.
# This is a real version mismatch in the project's own frozen stack
# (ml/requirements.txt pins pysheds>=0.4 + numpy>=1.26, which resolve to
# pysheds 0.5 + numpy 2.5.x -- incompatible as installed). Restoring the
# alias here is a local, non-invasive fix -- it does not modify pysheds,
# numpy, or any other repo file. Worth flagging to the team as a pinning
# bug in ml/requirements.txt; not fixed here since that file is Phase 6+
# owned, outside this session's scope.
if not hasattr(np, "in1d"):
    np.in1d = np.isin

import rasterio
from rasterio.transform import rowcol
from scipy.ndimage import distance_transform_edt, generic_filter
from pysheds.grid import Grid as PyshedsGrid

REPO_ROOT = Path(__file__).resolve().parents[3]
STREAM_ACC_THRESHOLD = 100     # same threshold as static_features.py
DRAINAGE_BUFFER_M = 1000.0     # 1km radius window for point-based drainage_density

LAT_APPROX_DEFAULT = 10.0
M_PER_DEG_LAT = 111320.0


def m_per_deg_lon(lat_deg: float) -> float:
    return 111320.0 * math.cos(math.radians(lat_deg))


# ---------------------------------------------------------------------------
# Region configs
# ---------------------------------------------------------------------------
REGIONS = {
    "Wayanad": {
        "dem": REPO_ROOT / "data" / "terrain" / "dem_wayanad.tif",
        "points": {
            # Same coordinates as ml/features/static_features.py's VILLAGES dict
            # (read-only reuse -- not modifying that file).
            "Mundakkai":     (11.5185, 76.0524),
            "Chooralmala":   (11.5143, 76.0498),
            "Attamala":      (11.5220, 76.0570),
            "Punjirimattom": (11.5100, 76.0450),
        },
    },
    "Idukki": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_idukki.tif",
        "points": {
            # Confirmed real sub-locations only (per Step 4 decision: use
            # district HQ as the representative point for district-level-only
            # events; do NOT invent per-event coordinates).
            "Munnar_town":            (10.0889, 77.0595),
            "Pettimudi_Rajamala":     (10.1683, 77.0114),   # verified via web search, 2020 landslide
            "Idamalayar_Dam":         (10.2062, 76.8496),
            "Idukki_Arch_Dam":        (9.8447, 76.9744),
            "Idukki_district_centroid_proxy_Painavu": (9.8497, 76.9744),  # district HQ town, per user decision
        },
    },
    "Rudraprayag": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_rudraprayag.tif",
        "points": {
            "Rudraprayag_town": (30.2849, 78.9810),  # district HQ, Alaknanda/Mandakini confluence
            "Kedarnath":        (30.7346, 79.0669),  # 2013 disaster site (real, verified)
            "Guptkashi":        (30.5333, 79.0833),  # Mandakini valley town
        },
    },
    "Chamoli": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_chamoli.tif",
        "points": {
            "Joshimath":  (30.5622, 79.5641),  # 2021 glacier disaster area (real, verified)
            "Gopeshwar":  (30.3936, 79.3159),  # district HQ
            "Badrinath":  (30.7433, 79.4938),
        },
    },
    "Ribhoi": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_ribhoi.tif",
        "points": {
            "Nongpoh_town_district_HQ": (25.9167, 91.8833),
            "Byrnihat":                 (25.9667, 91.8667),
        },
    },
    "Nilgiris": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_nilgiris.tif",
        "points": {
            "Ooty_Udhagamandalam_district_HQ": (11.4064, 76.6932),
            "Coonoor":                         (11.3530, 76.7959),
            "Gudalur":                         (11.5000, 76.4833),  # landslide-prone, adjoins Wayanad
        },
    },
    "Sikkim": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_sikkim.tif",
        "points": {
            "Mangan_district_HQ": (27.5167, 88.5333),
            "Chungthang":         (27.6167, 88.6333),  # Oct 2023 South Lhonak GLOF/Teesta disaster site (real, verified)
            "Lachen":             (27.7167, 88.5500),
        },
    },
    "Darjeeling": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_darjeeling.tif",
        "points": {
            "Darjeeling_town_district_HQ": (27.0410, 88.2663),
            "Kalimpong_town_district_HQ":  (27.0670, 88.4700),
            "Kurseong":                    (26.8809, 88.2809),  # NH55 landslide-prone town
        },
    },
    "Kullu": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_kullu.tif",
        "points": {
            "Kullu_town_district_HQ": (31.9576, 77.1095),
            "Manali":                 (32.2432, 77.1892),  # 2023 Beas flash-flood site (real, verified)
            "Bhuntar":                (31.8830, 77.1520),   # Beas/Parvati confluence area
        },
    },
    "Dhemaji": {
        "dem": REPO_ROOT / "data" / "multiregion" / "terrain" / "dem_dhemaji.tif",
        "points": {
            "Dhemaji_town_district_HQ": (27.4833, 94.5667),
            "Jonai":                    (27.7500, 95.1167),  # subdivision town near Arunachal foothills, Siang system
            "Gogamukh":                 (27.3500, 94.3500),  # western subdivision, Brahmaputra floodplain
        },
    },
}

OUT_PATH = REPO_ROOT / "data" / "multiregion" / "events" / "terrain_features_points.json"


def sample_at_point(array: np.ndarray, transform, lat: float, lon: float) -> float | None:
    try:
        row, col = rowcol(transform, lon, lat)
        if 0 <= row < array.shape[0] and 0 <= col < array.shape[1]:
            val = array[row, col]
            if np.isfinite(val):
                return float(val)
        return None
    except Exception:
        return None


def compute_region(region_name: str, cfg: dict) -> dict:
    dem_path = cfg["dem"]
    if not dem_path.exists():
        print(f"ERROR: DEM not found for {region_name}: {dem_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[{region_name}] Loading DEM: {dem_path}")
    with rasterio.open(dem_path) as src:
        dem_arr = src.read(1).astype(float)
        transform = src.transform
        nodata = src.nodata
        height, width = src.height, src.width
        dx_deg = abs(transform.a)
        dy_deg = abs(transform.e)

    lat_mean = np.mean([p[0] for p in cfg["points"].values()])
    dx_m = dx_deg * m_per_deg_lon(lat_mean)
    dy_m = dy_deg * M_PER_DEG_LAT
    cell_size_m = math.sqrt(dx_m * dy_m)

    if nodata is not None:
        dem_arr[dem_arr == nodata] = np.nan

    print(
        f"[{region_name}] Array {width}x{height}, cell ~{cell_size_m:.1f} m, "
        f"elev range [{np.nanmin(dem_arr):.0f}-{np.nanmax(dem_arr):.0f} m]"
    )

    # Slope / aspect
    dzdx = np.gradient(np.where(np.isfinite(dem_arr), dem_arr, 0.0), axis=1) / dx_m
    dzdy = np.gradient(np.where(np.isfinite(dem_arr), dem_arr, 0.0), axis=0) / dy_m
    slope_rad = np.arctan(np.sqrt(dzdx**2 + dzdy**2))
    slope_deg_arr = np.degrees(slope_rad)
    aspect_arr = (np.degrees(np.arctan2(-dzdx, dzdy)) + 360.0) % 360.0

    # TRI
    def _tri_kernel(values):
        center = values[4]
        neigh = np.concatenate([values[:4], values[5:]])
        finite = neigh[np.isfinite(neigh)]
        if len(finite) == 0 or not np.isfinite(center):
            return np.nan
        return float(np.mean(np.abs(finite - center)))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tri_arr = generic_filter(dem_arr, _tri_kernel, size=3, mode="reflect")

    # pysheds flow routing -- ONLY terrain library for this (CLAUDE.md)
    print(f"[{region_name}] Running pysheds flow routing ...")
    grid = PyshedsGrid.from_raster(str(dem_path))
    dem_raster = grid.read_raster(str(dem_path))
    flooded = grid.fill_depressions(dem_raster)
    inflated = grid.resolve_flats(flooded)
    fdir = grid.flowdir(inflated)
    acc = grid.accumulation(fdir)
    acc_arr = np.array(acc).astype(float)

    sca = (acc_arr + 1.0) * cell_size_m
    slope_rad_clamped = np.where(slope_rad < 0.001, 0.001, slope_rad)
    twi_arr = np.log(sca / np.tan(slope_rad_clamped))
    twi_arr[~np.isfinite(dem_arr)] = np.nan

    streams_bool = acc_arr > STREAM_ACC_THRESHOLD
    print(
        f"[{region_name}] Stream network: {streams_bool.sum()} cells "
        f"(threshold={STREAM_ACC_THRESHOLD}, ~{STREAM_ACC_THRESHOLD * cell_size_m**2 / 1e6:.3f} km2 upslope)"
    )
    dist_to_stream_m_arr = distance_transform_edt(~streams_bool, sampling=[dy_m, dx_m])

    buffer_px_y = max(1, int(round(DRAINAGE_BUFFER_M / dy_m)))
    buffer_px_x = max(1, int(round(DRAINAGE_BUFFER_M / dx_m)))
    buffer_area_km2 = (2 * DRAINAGE_BUFFER_M) * (2 * DRAINAGE_BUFFER_M) / 1e6

    results = {}
    for name, (lat, lon) in cfg["points"].items():
        row, col = rowcol(transform, lon, lat)
        in_bounds = 0 <= row < height and 0 <= col < width
        if not in_bounds:
            print(f"  WARNING: {name} ({lat},{lon}) falls outside the DEM bbox -- all null", file=sys.stderr)
            results[name] = {k: None for k in [
                "lat", "lon", "elevation", "slope_deg", "aspect", "TWI", "TRI",
                "distance_to_river_m", "flow_accumulation_cells", "drainage_density_km_per_km2",
            ]}
            continue

        elevation = sample_at_point(dem_arr, transform, lat, lon)
        slope_deg = sample_at_point(slope_deg_arr, transform, lat, lon)
        aspect = sample_at_point(aspect_arr, transform, lat, lon)
        twi = sample_at_point(twi_arr, transform, lat, lon)
        tri = sample_at_point(tri_arr, transform, lat, lon)
        dist_stream = sample_at_point(dist_to_stream_m_arr, transform, lat, lon)
        flow_acc = sample_at_point(acc_arr, transform, lat, lon)

        r0, r1 = max(0, row - buffer_px_y), min(height, row + buffer_px_y)
        c0, c1 = max(0, col - buffer_px_x), min(width, col + buffer_px_x)
        stream_px_in_buffer = int(streams_bool[r0:r1, c0:c1].sum())
        stream_len_km = (stream_px_in_buffer * cell_size_m) / 1000.0
        drainage_density = stream_len_km / buffer_area_km2 if buffer_area_km2 > 0 else None

        results[name] = {
            "lat": lat, "lon": lon,
            "elevation":                   round(elevation, 2) if elevation is not None else None,
            "slope_deg":                   round(slope_deg, 3) if slope_deg is not None else None,
            "aspect":                      round(aspect, 2) if aspect is not None else None,
            "TWI":                         round(twi, 4) if twi is not None else None,
            "TRI":                         round(tri, 3) if tri is not None else None,
            "distance_to_river_m":         round(dist_stream, 1) if dist_stream is not None else None,
            "flow_accumulation_cells":     round(flow_acc, 1) if flow_acc is not None else None,
            "drainage_density_km_per_km2": round(drainage_density, 4) if drainage_density is not None else None,
        }

    return results


def main():
    all_results = {}
    for region_name, cfg in REGIONS.items():
        all_results[region_name] = compute_region(region_name, cfg)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(all_results, indent=2))

    print("\n" + "=" * 90)
    print("REAL TERRAIN FEATURES -- point-sampled from actual SRTM 30m DEM (pysheds flow routing)")
    print("=" * 90)
    for region_name, pts in all_results.items():
        for name, feats in pts.items():
            print(f"\n[{region_name}] {name}  ({feats['lat']}, {feats['lon']})")
            for k, v in feats.items():
                if k in ("lat", "lon"):
                    continue
                print(f"    {k:32s} {v}")

    print(f"\nSaved -> {OUT_PATH}")


if __name__ == "__main__":
    main()
