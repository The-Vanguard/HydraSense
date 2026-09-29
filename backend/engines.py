"""
backend/engines.py -- Phase 4: Physics Engines (E2 and E3)

Implements:
  Gap Analysis Phase 4 / v2 Section 7.2-7.3
  - E2: Infinite-slope FS Monte-Carlo, P(FS<1), FS band penalty
  - E2: Rainfall intensity-duration (I-D) threshold (R_int)
  - E3: SCS-CN runoff, Kirpich Tc, SCS peak discharge (qp)

Owner: Phase 4 migration
"""

import math
import numpy as np
from typing import Dict, Any, Tuple


# --- E2: Infinite Slope Model (Section 7.2) ---

def run_e2_landslide(
    slope_deg: float,
    soil_depth_m: float,
    cohesion_kpa: float,
    friction_angle_deg: float,
    unit_weight_kn_m3: float,
    saturation_ratio: float,
    has_local_calibration: bool = True,
    num_samples: int = 1000
) -> Dict[str, Any]:
    """
    E2: Infinite-slope FS Monte-Carlo over soil parameters and depth (v2 §7.2).
    
    Draws parameters from a normal distribution around the mean, computes FS,
    and returns P(FS < 1) and the FS uncertainty band.
    """
    if slope_deg < 5.0:
        # Too flat for landslide
        return {
            "factor_of_safety": 5.0,
            "factor_of_safety_min": 5.0,
            "factor_of_safety_max": 5.0,
            "p_fs_less_than_1": 0.0,
            "fs_band_penalty": 0.0,
            "fs_band_widened": not has_local_calibration
        }

    beta_rad = math.radians(slope_deg)
    gamma_w = 9.81  # unit weight of water, kN/m3
    
    # 1. Sample distributions (v2 §7.2: Monte Carlo over parameters)
    # Soil depth is highly sensitive; give it 30% CoV if uncalibrated, else 15%
    z_cov = 0.15 if has_local_calibration else 0.30
    z_samples = np.random.normal(soil_depth_m, soil_depth_m * z_cov, num_samples)
    z_samples = np.clip(z_samples, 0.5, 10.0) # bound depth
    
    c_samples = np.random.normal(cohesion_kpa, cohesion_kpa * 0.2, num_samples)
    c_samples = np.clip(c_samples, 0.0, None)
    
    phi_samples = np.random.normal(friction_angle_deg, friction_angle_deg * 0.1, num_samples)
    phi_rad_samples = np.radians(np.clip(phi_samples, 5.0, 45.0))
    
    gamma_samples = np.random.normal(unit_weight_kn_m3, unit_weight_kn_m3 * 0.05, num_samples)
    
    # Root cohesion (added from land cover in v2)
    c_root = 2.0  # nominal baseline root cohesion in kPa (could be dynamically mapped from WorldCover)
    
    # Infinite slope equation
    # FS = [c' + c_root + (gamma_m - m*gamma_w)*z*cos(beta)^2 * tan(phi')] / [gamma_m*z*sin(beta)*cos(beta)]
    m = saturation_ratio
    
    cos_b = math.cos(beta_rad)
    sin_b = math.sin(beta_rad)
    
    numerator = c_samples + c_root + (gamma_samples - m * gamma_w) * z_samples * (cos_b**2) * np.tan(phi_rad_samples)
    denominator = gamma_samples * z_samples * sin_b * cos_b
    
    fs_samples = numerator / (denominator + 1e-6)
    
    fs_p50 = float(np.median(fs_samples))
    fs_p05 = float(np.percentile(fs_samples, 5))
    fs_p95 = float(np.percentile(fs_samples, 95))
    
    p_fail = float(np.sum(fs_samples < 1.0) / num_samples)
    
    # FS band penalty (v2 §7.2.2)
    # FS_band_penalty = min(0.6, (FS_p95 - FS_p05) / (2*FS_p50)) * w
    w = 1.0 if has_local_calibration else 1.5
    band_penalty = min(0.6, (fs_p95 - fs_p05) / (2.0 * max(fs_p50, 0.1))) * w
    
    return {
        "factor_of_safety": fs_p50,
        "factor_of_safety_min": fs_p05,
        "factor_of_safety_max": fs_p95,
        "p_fs_less_than_1": p_fail,
        "fs_band_penalty": band_penalty,
        "fs_band_widened": not has_local_calibration
    }

def compute_id_threshold(
    intensity_mm_hr: float,
    duration_hr: float,
    alpha: float = 14.82, # Caine (1980) baseline or regional fit
    beta: float = 0.39
) -> float:
    """
    E2: Rainfall intensity-duration (I-D) threshold exceedance (v2 §7.2.3).
    Returns R_int = I_obs / I_threshold(D)
    """
    if duration_hr <= 0 or intensity_mm_hr <= 0:
        return 0.0
    
    i_threshold = alpha * (duration_hr ** -beta)
    r_int = intensity_mm_hr / i_threshold
    return r_int


# --- E3: Micro-catchment Flood Engine (Section 7.3) ---

def run_e3_flood(
    rainfall_mm: float,
    rainfall_duration_hr: float,
    basin_area_km2: float,
    flow_length_m: float,
    basin_slope_m_m: float,
    curve_number: float,
    antecedent_moisture_condition: int = 2,
) -> Dict[str, Any]:
    """
    E3: Micro-catchment runoff and flood engine (v2 §7.3).
    """
    if rainfall_mm <= 0 or basin_area_km2 <= 0:
        return {
            "runoff_depth_mm": 0.0,
            "time_of_concentration_hr": 0.0,
            "peak_discharge_m3_s": 0.0,
            "flood_indicator": 0.0
        }
        
    # Adjust CN for Antecedent Moisture Condition (AMC)
    cn = curve_number
    if antecedent_moisture_condition == 1:
        # Dry
        cn = (4.2 * curve_number) / (10 - 0.058 * curve_number)
    elif antecedent_moisture_condition == 3:
        # Wet
        cn = (23 * curve_number) / (10 + 0.13 * curve_number)
        
    cn = max(30.0, min(98.0, cn))
    
    # Runoff depth (SCS-CN)
    # S = 25400/CN - 254 (mm)
    s = (25400.0 / cn) - 254.0
    ia = 0.2 * s
    
    if rainfall_mm > ia:
        q_runoff_mm = ((rainfall_mm - ia) ** 2) / (rainfall_mm - ia + s)
    else:
        q_runoff_mm = 0.0
        
    # Time of concentration (Kirpich)
    # Tc = 0.0195 * L^0.77 * S^(-0.385) in minutes
    if flow_length_m > 0 and basin_slope_m_m > 0:
        tc_min = 0.0195 * (flow_length_m ** 0.77) * (basin_slope_m_m ** -0.385)
    else:
        tc_min = 60.0 # fallback 1 hr
        
    tc_hr = tc_min / 60.0
    
    # Peak discharge (SCS triangular hydrograph)
    # Tp = D/2 + 0.6*Tc
    # qp = 0.208*A*Q / Tp
    
    duration = max(0.5, rainfall_duration_hr)
    tp_hr = (duration / 2.0) + (0.6 * tc_hr)
    
    if tp_hr > 0:
        qp_m3s = (0.208 * basin_area_km2 * q_runoff_mm) / tp_hr
    else:
        qp_m3s = 0.0
        
    # Flood indicator: normalize by basin area (m3/s per km2)
    # For a severe flash flood, specific peak discharge might exceed 5-10 m3/s/km2
    specific_discharge = qp_m3s / basin_area_km2 if basin_area_km2 > 0 else 0
    flood_indicator = min(1.0, specific_discharge / 15.0) # scale 0-1 (15 is extreme)

    return {
        "runoff_depth_mm": q_runoff_mm,
        "time_of_concentration_hr": tc_hr,
        "peak_discharge_m3_s": qp_m3s,
        "flood_indicator": flood_indicator
    }

