"""
tests/test_engines.py -- Phase 4 gate: verify FS and runoff.

Gap Analysis Phase 4 gate requirement:
  "FS and runoff verified by hand on one documented real event."

Event: Wayanad 2024 (Mundakkai)
Rainfall: 162 mm in 24h, intense burst 45 mm in 3h
Basin: ~4 km2, slope 25 deg, soil depth 2.5m
"""
import sys
import math
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.engines import run_e2_landslide, run_e3_flood, compute_id_threshold

def test_wayanad_2024_landslide_fs():
    """Verify infinite-slope FS drops below 1.0 at high saturation for Wayanad event."""
    
    # 1. Dry conditions (FS should be > 1.0)
    dry_result = run_e2_landslide(
        slope_deg=35.0, # Wayanad slopes are often 30-40 degrees
        soil_depth_m=2.5,
        cohesion_kpa=8.0,
        friction_angle_deg=28.0,
        unit_weight_kn_m3=18.5,
        saturation_ratio=0.3,
        has_local_calibration=True
    )
    assert dry_result["factor_of_safety"] > 1.0
    assert dry_result["p_fs_less_than_1"] < 0.3
    
    # 2. Saturated conditions (Wayanad July 30 2024)
    wet_result = run_e2_landslide(
        slope_deg=35.0,
        soil_depth_m=2.5,
        cohesion_kpa=8.0,
        friction_angle_deg=28.0,
        unit_weight_kn_m3=18.5,
        saturation_ratio=0.95, # Near saturation
        has_local_calibration=True
    )
    # FS should drop below 1.0
    assert wet_result["factor_of_safety"] < 1.0
    # High probability of failure
    assert wet_result["p_fs_less_than_1"] > 0.6
    
    # 3. Check uncertainty band widening for uncalibrated
    uncalibrated_result = run_e2_landslide(
        slope_deg=35.0,
        soil_depth_m=2.5,
        cohesion_kpa=8.0,
        friction_angle_deg=28.0,
        unit_weight_kn_m3=18.5,
        saturation_ratio=0.6,
        has_local_calibration=False
    )
    assert uncalibrated_result["fs_band_widened"] is True
    assert uncalibrated_result["fs_band_penalty"] > 0.0

def test_wayanad_2024_flood_runoff():
    """Verify SCS-CN and Kirpich runoff for Wayanad catchment."""
    
    # Chooralmala / Mundakkai catchment estimate
    # ~4 km2, flow length ~3000m, steep slope
    
    # Intense burst: 45 mm in 3 hours
    result = run_e3_flood(
        rainfall_mm=45.0,
        rainfall_duration_hr=3.0,
        basin_area_km2=4.0,
        flow_length_m=3000.0,
        basin_slope_m_m=0.3,
        curve_number=75.0,
        antecedent_moisture_condition=3 # AMC III (Wet)
    )
    
    # Runoff should be substantial
    assert result["runoff_depth_mm"] > 10.0
    
    # Steep catchment -> short time of concentration
    assert result["time_of_concentration_hr"] < 1.0
    
    # Peak discharge > 0
    assert result["peak_discharge_m3_s"] > 8.0
    
    # Flood indicator should be elevated
    assert result["flood_indicator"] > 0.15

def test_id_threshold():
    """Check rainfall I-D threshold (Caine)."""
    # 45 mm in 3h -> 15 mm/hr
    r_int = compute_id_threshold(intensity_mm_hr=15.0, duration_hr=3.0)
    # Caine 1980 threshold for 3h is 14.82 * 3^(-0.39) = 14.82 * 0.65 = ~9.6 mm/hr
    # 15 / 9.6 = 1.56
    assert r_int > 1.0 # exceeded
