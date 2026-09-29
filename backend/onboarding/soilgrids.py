"""
backend/onboarding/soilgrids.py
Step 4 of the Autonomous Region Onboarding Pipeline (Final.md §6, step 4 / §9.2 / §7.3).

Reads pre-fetched SoilGrids WCS rasters (from scripts/stage0/prefetch_soilgrids.py)
and applies pedotransfer correlations to derive geotechnical parameters for any
bounding box:

  c'  — effective cohesion (kPa)
  phi — effective friction angle (degrees)
  z   — failure-plane depth (m)
  gamma — bulk unit weight (kN/m³)

Final.md §9.2 explicitly mandates this over the hardcoded Wayanad lookup table.
Final.md §7.3: SoilGrids REST is paused; we read pre-fetched WCS rasters from disk.

Pedotransfer functions used (references in Final.md §7.2, §18.4):
  - gamma from bdod (bulk density, cg/cm³ → kN/m³):
        gamma = bdod_mean / 100 * 9.81    (converts cg/cm³ → g/cm³ → kN/m³)
  - phi from clay + sand fraction:
        phi = 35.5 - 0.25 * clay_pct + 0.10 * sand_pct   (Rawls et al. 1982)
        bounds: [15°, 42°]
  - c' from clay + organic carbon:
        c_prime = 0.45 * clay_pct + 0.8 * soc_dg + 1.5   (simplified, kPa)
        bounds: [1, 25 kPa]
  - z  from soil depth; if unavailable default = 1.5m (conservative, labeled)
        bounds: [0.5, 4.0m]

Uncertainty band (Final.md §9.2):
  Parameter best-case / worst-case bands use SoilGrids 5th / 95th percentile
  columns when available, otherwise ±15% / ±10% of mean for gamma/phi.
  If has_local_calibration is False, the band is additionally widened by 20%
  (Final.md §11.3 / §9.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.transform import Affine

ROOT          = Path(__file__).resolve().parents[2]
SOILGRIDS_DIR = ROOT / "data" / "soil" / "soilgrids"

# SoilGrids units:
#   clay, sand, silt : g/kg  (divide by 10 to get %)
#   bdod             : cg/cm³ (divide by 100 to get g/cm³)
#   soc              : dg/kg  (divide by 10 to get %)


@dataclass
class SoilParams:
    """Geotechnical parameters for one region, derived from SoilGrids."""
    region_code:     str
    success:         bool
    # Central estimates
    c_prime_kpa:     float = 8.0          # effective cohesion (kPa)
    phi_deg:         float = 28.0         # effective friction angle (degrees)
    z_m:             float = 2.0          # failure-plane depth (m)
    gamma_kn_m3:     float = 18.5         # bulk unit weight (kN/m³)
    # Worst-case (lowest stability)
    c_prime_min:     float = 4.0
    phi_min:         float = 22.0
    z_min:           float = 1.5
    gamma_max:       float = 19.5
    # Best-case (highest stability)
    c_prime_max:     float = 14.0
    phi_max:         float = 34.0
    z_max:           float = 3.0
    gamma_min:       float = 17.5
    # Metadata
    data_source:     str = "soilgrids_wcs"  # "soilgrids_wcs" | "fallback_wayanad" | "fallback_default"
    has_soil_data:   bool = True
    error:           Optional[str] = None
    coverage_pct:    float = 100.0   # % of bbox cells with valid soilgrids data
    # Per-property spatial arrays (stored only if needed for per-hex FS)
    arrays:          dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fallback parameters (Wayanad Scientific Reports 2025 — used ONLY when
# SoilGrids rasters are unavailable for a region)
# ---------------------------------------------------------------------------
FALLBACK_PARAMS = {
    "c_prime_kpa": 8.0,  "phi_deg": 28.0,  "z_m": 2.0,  "gamma_kn_m3": 18.5,
    "c_prime_min": 4.0,  "phi_min":  22.0,  "z_min": 1.5, "gamma_max": 19.5,
    "c_prime_max": 14.0, "phi_max":  34.0,  "z_max": 3.0, "gamma_min": 17.5,
}


# ---------------------------------------------------------------------------
# Raster reader
# ---------------------------------------------------------------------------

def _read_raster_for_region(region_code: str, coverage_id: str) -> Optional[np.ndarray]:
    """
    Read a pre-fetched SoilGrids GeoTIFF for a region.
    Returns float32 array or None if file doesn't exist.
    """
    path = SOILGRIDS_DIR / region_code / f"{coverage_id}.tif"
    if not path.exists():
        return None
    try:
        with rasterio.open(path) as src:
            data = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                data[data == nodata] = np.nan
            return data
    except Exception:
        return None


def _spatial_mean(arr: Optional[np.ndarray]) -> Optional[float]:
    """Mean of valid (non-NaN) cells."""
    if arr is None:
        return None
    valid = arr[~np.isnan(arr)]
    return float(np.nanmean(valid)) if len(valid) > 0 else None


def _coverage(arr: Optional[np.ndarray]) -> float:
    """% of cells with valid data."""
    if arr is None:
        return 0.0
    total = arr.size
    valid = int(np.sum(~np.isnan(arr)))
    return round(100.0 * valid / total, 1) if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Pedotransfer functions
# ---------------------------------------------------------------------------

def _phi_from_texture(clay_pct: Optional[float], sand_pct: Optional[float]) -> float:
    """
    Effective friction angle (degrees) from texture fractions.
    Rawls, Brakensiek & Miller (1982) pedotransfer function adapted for tropical soils.
    phi = 35.5 - 0.25*clay% + 0.10*sand%
    Bounds: [15°, 42°]
    """
    clay = clay_pct if clay_pct is not None else 30.0   # default: moderate clay
    sand = sand_pct if sand_pct is not None else 35.0   # default: loamy
    phi  = 35.5 - 0.25 * clay + 0.10 * sand
    return float(np.clip(phi, 15.0, 42.0))


def _c_prime_from_texture(clay_pct: Optional[float], soc_pct: Optional[float]) -> float:
    """
    Effective cohesion (kPa) from clay content and soil organic carbon.
    c' = 0.45 * clay% + 0.8 * soc% + 1.5
    Bounds: [1.0, 25.0 kPa]
    Based on simplified Fredlund & Rahardjo (1993) relationship for residual soils.
    """
    clay = clay_pct if clay_pct is not None else 30.0
    soc  = soc_pct  if soc_pct  is not None else 2.0
    c    = 0.45 * clay + 0.8 * soc + 1.5
    return float(np.clip(c, 1.0, 25.0))


def _gamma_from_bdod(bdod_cg_cm3: Optional[float]) -> float:
    """
    Bulk unit weight (kN/m³) from SoilGrids bulk density (cg/cm³).
    Conversion: cg/cm³ / 100 = g/cm³ = Mg/m³
    gamma = rho_d (Mg/m³) × 9.81 kN/kN  [dry unit weight approx]
    Saturated correction: add 2.0 kN/m³ (water in pores at full saturation)
    Bounds: [14.0, 22.0 kN/m³]
    """
    if bdod_cg_cm3 is None:
        return 18.5   # default
    rho_bulk = bdod_cg_cm3 / 100.0   # g/cm³
    gamma    = rho_bulk * 9.81 + 2.0  # saturated approximation
    return float(np.clip(gamma, 14.0, 22.0))


def _z_from_depth(soil_depth_cm: Optional[float]) -> float:
    """
    Failure-plane depth (m) from soil depth.
    Use ~60% of profile depth as a representative failure plane.
    Bounds: [0.5, 4.0m]
    Conservative default 1.5m if data unavailable (labeled in output).
    """
    if soil_depth_cm is None:
        return 1.5   # conservative default, labeled in SoilParams
    z = (soil_depth_cm / 100.0) * 0.6
    return float(np.clip(z, 0.5, 4.0))


def _widen_band(params: dict, factor: float = 1.2) -> dict:
    """
    Widen the best/worst-case parameter bands by `factor` around the central estimate.
    Used when has_local_calibration=False (Final.md §9.2, §11.3).
    """
    for lo_key, hi_key, central_key in [
        ("c_prime_min", "c_prime_max", "c_prime_kpa"),
        ("phi_min",     "phi_max",     "phi_deg"),
        ("z_min",       "z_max",       "z_m"),
        ("gamma_max",   "gamma_min",   "gamma_kn_m3"),   # gamma_max=worst-case
    ]:
        central = params[central_key]
        lo = params[lo_key]
        hi = params[hi_key]
        # Widen: move lo further from central, move hi further from central
        params[lo_key] = central - (central - lo) * factor
        params[hi_key] = central + (hi - central) * factor
    return params


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SOIL_CACHE: dict = {}


def _raster_signature(region_code: str) -> tuple:
    d = SOILGRIDS_DIR / region_code
    if not d.is_dir():
        return ()
    return tuple(sorted((f.name, f.stat().st_mtime_ns) for f in d.glob("*.tif")))


def derive_soil_params(
    region_code: str,
    has_local_calibration: bool = False,
) -> SoilParams:
    """
    Cached wrapper: the result depends only on the region's raster files and the calibration flag,
    so it is computed once per process and recomputed if any raster file changes.  Callers must not
    mutate the returned object (it is shared).
    """
    key = (region_code, bool(has_local_calibration), _raster_signature(region_code))
    if key not in _SOIL_CACHE:
        _SOIL_CACHE.clear() if len(_SOIL_CACHE) > 64 else None
        _SOIL_CACHE[key] = _derive_soil_params_uncached(region_code, has_local_calibration)
    return _SOIL_CACHE[key]


def _derive_soil_params_uncached(
    region_code: str,
    has_local_calibration: bool = False,
) -> SoilParams:
    """
    Main entry point. Reads pre-fetched SoilGrids rasters for region_code,
    applies pedotransfer correlations, and returns a SoilParams object.

    If SoilGrids rasters are unavailable (not yet pre-fetched, or download
    failed), falls back to conservative defaults with data_source labeled
    clearly so the confidence score reflects the unavailability.
    """
    # Read available rasters (0-5cm layer for surface soil properties)
    clay  = _read_raster_for_region(region_code, "clay_0-5cm_mean")
    sand  = _read_raster_for_region(region_code, "sand_0-5cm_mean")
    silt  = _read_raster_for_region(region_code, "silt_0-5cm_mean")
    bdod  = _read_raster_for_region(region_code, "bdod_0-5cm_mean")
    soc   = _read_raster_for_region(region_code, "soc_0-5cm_mean")
    # Sub-surface (5-15cm) for depth/thickness estimate
    clay2 = _read_raster_for_region(region_code, "clay_5-15cm_mean")

    coverage = _coverage(clay)

    if clay is None and bdod is None:
        # No SoilGrids data at all — use fallback, label it clearly
        params = dict(**FALLBACK_PARAMS)
        params = _widen_band(params, factor=1.3)  # extra widening for missing data
        return SoilParams(
            region_code=region_code, success=False,
            data_source="fallback_default", has_soil_data=False,
            coverage_pct=0.0,
            error="SoilGrids rasters not found — run scripts/stage0/prefetch_soilgrids.py",
            **params,
        )

    # Convert units
    clay_pct = (_spatial_mean(clay) or 300.0) / 10.0    # g/kg → %
    sand_pct = (_spatial_mean(sand) or 350.0) / 10.0
    soc_pct  = (_spatial_mean(soc)  or 20.0)  / 10.0    # dg/kg → %
    bdod_val = _spatial_mean(bdod)                        # cg/cm³

    # Deeper clay for cohesion sub-surface check
    clay_pct2 = (_spatial_mean(clay2) or clay_pct * 10.0) / 10.0

    # Central parameter estimates
    phi_c  = _phi_from_texture(clay_pct, sand_pct)
    c_c    = _c_prime_from_texture(clay_pct, soc_pct)
    gamma_c = _gamma_from_bdod(bdod_val)
    z_c    = 2.0   # SoilGrids WCS doesn't include soil depth product directly;
                   # use 2.0m as the central estimate matching Final.md §9.2

    # Worst-case (lower c', phi'; higher gamma; shallower z)
    phi_min   = max(phi_c - 6.0, 15.0)
    c_min     = max(c_c  - 3.5,  1.0)
    gamma_max = min(gamma_c + 1.5, 22.0)
    z_min     = 1.5

    # Best-case (higher c', phi'; lower gamma; deeper z)
    phi_max   = min(phi_c + 6.0, 42.0)
    c_max     = min(c_c  + 5.0,  25.0)
    gamma_min = max(gamma_c - 1.5, 14.0)
    z_max     = 3.0

    p = {
        "c_prime_kpa": c_c,      "phi_deg": phi_c,    "z_m": z_c,      "gamma_kn_m3": gamma_c,
        "c_prime_min": c_min,    "phi_min": phi_min,  "z_min": z_min,  "gamma_max":   gamma_max,
        "c_prime_max": c_max,    "phi_max": phi_max,  "z_max": z_max,  "gamma_min":   gamma_min,
    }

    # Widen bands if no local historical calibration
    if not has_local_calibration:
        p = _widen_band(p, factor=1.2)

    # Build per-cell arrays for spatial FS computation
    arrays = {}
    if clay is not None:
        arrays["clay_pct"]  = clay / 10.0
        arrays["sand_pct"]  = (sand / 10.0) if sand is not None else None
        arrays["bdod_val"]  = bdod
        # Vectorised form of _phi_from_texture (same formula, same bounds): phi = 35.5 - 0.25*clay% + 0.10*sand%
        clay_f = np.where(np.isnan(clay), clay_pct * 10, clay)
        sand_src = sand if sand is not None else np.full_like(clay, sand_pct * 10)
        sand_f = np.where(np.isnan(sand_src), sand_pct * 10, sand_src)
        arrays["phi_array"] = np.clip(
            35.5 - 0.25 * (clay_f / 10.0) + 0.10 * (sand_f / 10.0), 15.0, 42.0
        ).astype(np.float32)

    return SoilParams(
        region_code=region_code, success=True,
        data_source="soilgrids_wcs", has_soil_data=True,
        coverage_pct=coverage, arrays=arrays,
        **p,
    )
