import sys
sys.path.insert(0, '.')
from ml.models.factor_of_safety import (
    compute_fs_for_region, compute_fs_from_soilgrids, widen_fs_band
)
from backend.onboarding.soilgrids import SoilParams

# Test 1: widen_fs_band
mid, lo, hi = widen_fs_band(1.5, 1.0, 2.5, widen_factor=1.2)
assert lo < 1.0 and hi > 2.5, "Band not widened"
print("[PASS] widen_fs_band: %.3f < %.3f < %.3f" % (lo, mid, hi))

# Test 2: compute_fs_from_soilgrids (calibrated)
sp = SoilParams(
    region_code='rudraprayag-uk', success=True,
    c_prime_kpa=7.5, phi_deg=30.0, z_m=1.8, gamma_kn_m3=18.0,
    c_prime_min=4.0, phi_min=24.0, z_min=1.2, gamma_max=19.5,
    c_prime_max=13.0, phi_max=36.0, z_max=3.0, gamma_min=17.0,
    data_source='soilgrids_wcs',
)
r_cal = compute_fs_from_soilgrids(28.5, 0.65, sp, has_local_calibration=True)
assert r_cal['factor_of_safety'] is not None
assert r_cal['factor_of_safety_min'] <= r_cal['factor_of_safety'] <= r_cal['factor_of_safety_max']
assert r_cal['band_widened'] == False
assert r_cal['parameter_source'] == 'soilgrids_wcs'
print("[PASS] compute_fs_from_soilgrids (calibrated): FS=%.4f band_widened=%s" % (
    r_cal['factor_of_safety'], r_cal['band_widened']))

# Test 3: uncalibrated — band should be wider
r_uncal = compute_fs_from_soilgrids(28.5, 0.65, sp, has_local_calibration=False)
assert r_uncal['band_widened'] == True
assert r_uncal['factor_of_safety_min'] < r_cal['factor_of_safety_min']
assert r_uncal['factor_of_safety_max'] > r_cal['factor_of_safety_max']
print("[PASS] compute_fs_from_soilgrids (uncalibrated): band_widened=%s" % r_uncal['band_widened'])
print("       Calibrated band:   %.3f - %.3f" % (r_cal['factor_of_safety_min'], r_cal['factor_of_safety_max']))
print("       Uncalibrated band: %.3f - %.3f" % (r_uncal['factor_of_safety_min'], r_uncal['factor_of_safety_max']))

# Test 4: fallback path (no soilgrids rasters for unknown region)
r_fallback = compute_fs_for_region(28.5, 0.65, 'unknown-region', has_local_calibration=True)
assert r_fallback['factor_of_safety'] is not None
assert r_fallback['parameter_source'] == 'fallback_wayanad'
print("[PASS] compute_fs_for_region (fallback): source=%s" % r_fallback['parameter_source'])

# Test 5: flat slope -> FS_FLAT
r_flat = compute_fs_from_soilgrids(0.0, 0.5, sp)
assert r_flat['factor_of_safety'] == 999.0
print("[PASS] Flat slope -> FS_FLAT=%.1f" % r_flat['factor_of_safety'])

# Test 6: missing input -> None
r_miss = compute_fs_from_soilgrids(None, 0.65, sp)
assert r_miss['factor_of_safety'] is None
assert 'slope_deg' in r_miss['missing_inputs']
print("[PASS] Missing slope_deg -> FS=None missing_inputs=%s" % r_miss['missing_inputs'])

print("\nStage 2 FS smoke test: ALL PASS")
