"""
Phase 5 unit tests — Factor of Safety model.

All hand-computed reference values verifiable with a calculator.
No rasters or network access required.

Tests:
  1. Hand-computed reference value at known inputs (β=35°, m=0.7, central params)
  2. min ≤ mid ≤ max for all pilot-range (slope, m) combinations
  3. Physical plausibility: FS in [0.5, 2.0] for high-saturation Wayanad conditions
  4. Flat slope (slope_deg ≤ 0) → FS = 999.0 for all three values
  5. FS < 1.0 at steep fully-saturated slope — verified failure condition
  6. Missing inputs → missing_inputs list populated, FS = None
  7. Punjirimattom hexes: no silent default — if slope_deg missing, FS = None
  8. Integration against real Phase 1 GWETROOT data (soil_moisture.json present check)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ml.models.factor_of_safety import (
    GAMMA_W,
    _PARAMS_BEST,
    _PARAMS_MID,
    _PARAMS_WORST,
    FS_FLAT,
    FS_MIN_CLIP,
    FS_MAX_CLIP,
    _fs,
    compute_factor_of_safety,
)

errors: list[str] = []


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _hand_compute_fs(c_prime, phi_deg, z, gamma, m, beta_deg):
    """
    Replicate the formula manually — independent of _fs() — for cross-check.
    FS = [c' + (gamma - gamma_w * m) * z * cos²(beta) * tan(phi')] /
         [gamma * z * sin(beta) * cos(beta)]
    """
    beta  = math.radians(beta_deg)
    phi   = math.radians(phi_deg)
    num   = c_prime + (gamma - GAMMA_W * m) * z * (math.cos(beta) ** 2) * math.tan(phi)
    den   = gamma * z * math.sin(beta) * math.cos(beta)
    return num / den


# ---------------------------------------------------------------------------
# Test 1 — Hand-computed reference at β=35°, m=0.7 (central params)
# ---------------------------------------------------------------------------
BETA_TEST = 35.0   # degrees
M_TEST    = 0.70   # GWETROOT — typical high-monsoon Wayanad value
TOL       = 1e-6   # tolerance for floating-point comparison

# Hand-computed expected value (show your working for reviewers):
#   beta = radians(35) ≈ 0.6109 rad
#   cos²(35°) = cos(35°)^2 ≈ (0.8192)^2 ≈ 0.6710
#   sin(35°)  ≈ 0.5736, cos(35°) ≈ 0.8192
#   tan(28°)  ≈ 0.5317
#   numerator  = 8.0 + (18.5 - 9.81×0.7) × 2.0 × 0.6710 × 0.5317
#              = 8.0 + (18.5 - 6.867) × 2.0 × 0.6710 × 0.5317
#              = 8.0 + 11.633 × 0.7141
#              = 8.0 + 8.308
#              ≈ 16.308
#   denominator = 18.5 × 2.0 × 0.5736 × 0.8192
#               = 18.5 × 2.0 × 0.4698
#               ≈ 17.382
#   FS ≈ 16.308 / 17.382 ≈ 0.9382
EXPECTED_MID = _hand_compute_fs(
    c_prime=_PARAMS_MID["c_prime"], phi_deg=_PARAMS_MID["phi_deg"],
    z=_PARAMS_MID["z"], gamma=_PARAMS_MID["gamma"], m=M_TEST, beta_deg=BETA_TEST,
)
actual_fs = _fs(
    c_prime=_PARAMS_MID["c_prime"], phi_deg=_PARAMS_MID["phi_deg"],
    z=_PARAMS_MID["z"], gamma=_PARAMS_MID["gamma"], m=M_TEST, beta_deg=BETA_TEST,
)
if abs(actual_fs - EXPECTED_MID) < TOL:
    print(
        f"[OK] Test 1: Hand-computed FS at beta={BETA_TEST} deg, m={M_TEST}: "
        f"expected {EXPECTED_MID:.6f}, got {actual_fs:.6f}"
    )
    # Also sanity-check the absolute value (~0.938 for these params)
    if not (0.5 <= EXPECTED_MID <= 2.0):
        errors.append(
            f"FAIL Test 1: FS={EXPECTED_MID:.4f} outside physical plausibility range [0.5, 2.0]"
        )
    else:
        print(f"[OK] Test 1: FS={EXPECTED_MID:.4f} is physically plausible (0.5–2.0 range)")
else:
    errors.append(
        f"FAIL Test 1: _fs() disagreed with hand computation. "
        f"Expected {EXPECTED_MID:.8f}, got {actual_fs:.8f}"
    )

# ---------------------------------------------------------------------------
# Test 2 — min ≤ mid ≤ max for the full pilot range of slopes and m values
# ---------------------------------------------------------------------------
SLOPE_RANGE = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
M_RANGE     = [0.0, 0.3, 0.5, 0.7, 0.85, 1.0]

fail_ordering = []
for slope in SLOPE_RANGE:
    for m in M_RANGE:
        r = compute_factor_of_safety(slope_deg=float(slope), soil_saturation_ratio=m)
        fmin = r["factor_of_safety_min"]
        fmid = r["factor_of_safety"]
        fmax = r["factor_of_safety_max"]
        if not (fmin <= fmid <= fmax):
            fail_ordering.append(
                f"slope={slope}° m={m}: min={fmin:.4f} mid={fmid:.4f} max={fmax:.4f}"
            )

if fail_ordering:
    for f in fail_ordering:
        errors.append(f"FAIL Test 2 (ordering): {f}")
else:
    print(
        f"[OK] Test 2: min≤mid≤max holds for all "
        f"{len(SLOPE_RANGE) * len(M_RANGE)} (slope, m) combinations"
    )

# ---------------------------------------------------------------------------
# Test 3 — Physical plausibility: FS_mid in [0.5, 2.0] for high-saturation
#          Wayanad pilot slopes (the range that matters for the risk model)
# ---------------------------------------------------------------------------
PLAUSIBLE_SLOPES = [20, 25, 30, 35, 40, 45]  # degrees — typical Wayanad hill slopes
PLAUSIBLE_M      = 0.85                        # high monsoon saturation (July 2024 event: ~0.87)

fail_plaus = []
for slope in PLAUSIBLE_SLOPES:
    r    = compute_factor_of_safety(slope_deg=float(slope), soil_saturation_ratio=PLAUSIBLE_M)
    fmid = r["factor_of_safety"]
    if not (0.5 <= fmid <= 2.0):
        fail_plaus.append(f"slope={slope}° FS_mid={fmid:.4f}")

if fail_plaus:
    for f in fail_plaus:
        errors.append(f"FAIL Test 3 (plausibility): {f}")
else:
    print(
        f"[OK] Test 3: FS_mid in [0.5, 2.0] for m={PLAUSIBLE_M} at slopes "
        f"{PLAUSIBLE_SLOPES} (physically plausible for Wayanad conditions)"
    )

# ---------------------------------------------------------------------------
# Test 4 — Flat slope → FS = FS_FLAT = 999.0 for all three values
# ---------------------------------------------------------------------------
for flat_slope in [0.0, -1.0, -5.0]:
    r = compute_factor_of_safety(slope_deg=flat_slope, soil_saturation_ratio=0.7)
    if r["factor_of_safety"] != FS_FLAT:
        errors.append(
            f"FAIL Test 4: slope={flat_slope}° should give FS=999.0, got {r['factor_of_safety']}"
        )
    elif r["factor_of_safety_min"] != FS_FLAT or r["factor_of_safety_max"] != FS_FLAT:
        errors.append(
            f"FAIL Test 4: flat slope min/max not FS_FLAT: "
            f"min={r['factor_of_safety_min']}, max={r['factor_of_safety_max']}"
        )
    elif r["fs_band_straddles_one"]:
        errors.append(f"FAIL Test 4: flat slope should not straddle FS=1.0")
print("[OK] Test 4: slope ≤ 0° → FS = FS_min = FS_max = 999.0, straddles_one = False")

# ---------------------------------------------------------------------------
# Test 5 — FS < 1.0 at steep saturated slope (verified failure condition)
#          At slope=45°, m=1.0, central params: this soil SHOULD fail.
#          Hand-compute to confirm:
#            beta=45°, m=1.0:
#            num = 8.0 + (18.5 - 9.81×1.0) × 2.0 × 0.5 × tan(28°)
#                = 8.0 + 8.69 × 2.0 × 0.5 × 0.5317
#                = 8.0 + 4.621 = 12.621  -- wait this gives > 1
#            Actually need to check: den = 18.5 × 2.0 × sin(45)×cos(45) = 18.5×2.0×0.5 = 18.5
#            FS = 12.621 / 18.5 ≈ 0.682  → < 1.0 ✓ (failure predicted)
# ---------------------------------------------------------------------------
r_steep = compute_factor_of_safety(slope_deg=45.0, soil_saturation_ratio=1.0)
fmid_steep = r_steep["factor_of_safety"]
if fmid_steep >= 1.0:
    errors.append(
        f"FAIL Test 5: At slope=45°, m=1.0 (fully saturated), FS_mid={fmid_steep:.4f} "
        f"should be < 1.0 for these soil params (failure condition for July 2024 event)"
    )
else:
    print(
        f"[OK] Test 5: slope=45°, m=1.0 → FS_mid={fmid_steep:.4f} < 1.0 "
        f"(slope failure predicted — matches July 2024 Mundakkai event conditions)"
    )

# Also verify the 1/FS inverse is > 1.0 (for fusion model usage)
fs_inverse = 1.0 / fmid_steep
if fs_inverse <= 1.0:
    errors.append(f"FAIL Test 5b: 1/FS={fs_inverse:.4f} should be > 1.0 when FS < 1.0")
else:
    print(f"[OK] Test 5b: 1/FS = {fs_inverse:.4f} > 1.0 (correct fusion-model input for failure case)")

# ---------------------------------------------------------------------------
# Test 6 — Missing inputs → missing_inputs list populated, FS values = None
# ---------------------------------------------------------------------------
cases_missing = [
    (None,  0.7,  ["slope_deg"]),
    (35.0,  None, ["soil_saturation_ratio"]),
    (None,  None, ["slope_deg", "soil_saturation_ratio"]),
]
for slope, m, expected_missing in cases_missing:
    r = compute_factor_of_safety(slope_deg=slope, soil_saturation_ratio=m)
    if sorted(r["missing_inputs"]) != sorted(expected_missing):
        errors.append(
            f"FAIL Test 6: slope={slope}, m={m} → missing_inputs={r['missing_inputs']}, "
            f"expected {expected_missing}"
        )
    elif r["factor_of_safety"] is not None:
        errors.append(
            f"FAIL Test 6: slope={slope}, m={m} → FS should be None when input missing"
        )
print("[OK] Test 6: Missing inputs correctly flagged; FS=None; never silently defaulted")

# ---------------------------------------------------------------------------
# Test 7 — Punjirimattom hexes: slope_deg=None → FS=None, not a silent zero
#          (Simulates the case where Phase 3 has not run and slope is unavailable.)
# ---------------------------------------------------------------------------
PUNJI_HEXES_9 = [
    "88600640b7fffff",  # village-core
    "88600640b1fffff", "88600640b3fffff", "8860064e59fffff",  # inner-slope
    "88600640b9fffff", "88600640bbfffff",  # upper-slope
    "8860064565fffff", "886006456dfffff", "8860064e5bfffff",  # upper-slope
]
any_silent_zero = False
for hid in PUNJI_HEXES_9:
    # Simulate Phase 3 not yet run: slope_deg = None
    r = compute_factor_of_safety(slope_deg=None, soil_saturation_ratio=0.85)
    if r["factor_of_safety"] is not None or r["factor_of_safety"] == 0.0:
        any_silent_zero = True
        errors.append(
            f"FAIL Test 7: Punjirimattom hex {hid} with slope_deg=None returned "
            f"FS={r['factor_of_safety']} instead of None"
        )
    if "slope_deg" not in r["missing_inputs"]:
        any_silent_zero = True
        errors.append(
            f"FAIL Test 7: Punjirimattom hex {hid} missing_inputs should contain 'slope_deg'"
        )
if not any_silent_zero:
    print(
        f"[OK] Test 7: All {len(PUNJI_HEXES_9)} Punjirimattom hexes with slope_deg=None → "
        f"FS=None, missing_inputs=['slope_deg'] (no silent default)"
    )

# ---------------------------------------------------------------------------
# Test 8 — Integration: real GWETROOT from Phase 1 soil_moisture.json
#          Just verify the file is readable and yields a sane value (0-1).
# ---------------------------------------------------------------------------
import json
sm_path = ROOT / "data" / "soil" / "soil_moisture.json"
if sm_path.exists():
    sm = json.loads(sm_path.read_text(encoding="utf-8", errors="replace"))
    locations = sm.get("locations", [])
    all_ok = True
    for loc in locations:
        series = loc.get("gwetroot_hourly") or {}
        # Find latest non-null
        gwet = next(
            (v for k, v in sorted(series.items(), reverse=True) if v is not None), None
        )
        if gwet is None:
            errors.append(
                f"FAIL Test 8: {loc.get('location')} has no non-null GWETROOT value in Phase 1 JSON"
            )
            all_ok = False
        elif not (0.0 <= gwet <= 1.0):
            errors.append(
                f"FAIL Test 8: {loc.get('location')} GWETROOT={gwet} outside [0,1]"
            )
            all_ok = False
        else:
            # Run FS at a representative slope (35° — near Mundakkai failure zone)
            r = compute_factor_of_safety(slope_deg=35.0, soil_saturation_ratio=gwet)
            if r["missing_inputs"]:
                errors.append(
                    f"FAIL Test 8: FS for {loc.get('location')} returned missing_inputs "
                    f"despite valid GWETROOT={gwet}"
                )
                all_ok = False
    if all_ok:
        print(
            f"[OK] Test 8: GWETROOT in [0,1] for all {len(locations)} villages in Phase 1 JSON; "
            f"FS computable at representative slope=35°"
        )
else:
    print(f"[SKIP] Test 8: soil_moisture.json not found at {sm_path} — Phase 1 not run yet")

# ---------------------------------------------------------------------------
# Test 9 — Parameter invariant: worst-case FS < best-case FS for any slope
#          (Validates that the parameter table is correctly oriented.)
# ---------------------------------------------------------------------------
for slope in [10, 20, 30, 40]:
    for m in [0.3, 0.7, 1.0]:
        fs_w = _fs(**_PARAMS_WORST, m=m, beta_deg=float(slope))
        fs_b = _fs(**_PARAMS_BEST,  m=m, beta_deg=float(slope))
        if fs_w > fs_b:
            errors.append(
                f"FAIL Test 9: At slope={slope}°, m={m}: worst FS ({fs_w:.4f}) > "
                f"best FS ({fs_b:.4f}) — parameter table orientation is wrong"
            )
if not any("FAIL Test 9" in e for e in errors):
    print("[OK] Test 9: worst-case FS < best-case FS for all tested (slope, m) pairs")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
if errors:
    for e in errors:
        print(e)
    print(f"\n{len(errors)} TEST(S) FAILED")
    sys.exit(1)
else:
    print("=" * 65)
    print("ALL PHASE 5 UNIT TESTS PASSED")
    print("factor_of_safety.py verified:")
    print("  - Hand-computed FS matches formula exactly")
    print("  - min ≤ mid ≤ max for all pilot-range inputs")
    print("  - FS physically plausible (0.5–2.0) for Wayanad conditions")
    print("  - Flat slopes → 999.0, no division by zero")
    print("  - Steep saturated slope → FS < 1.0 (failure predicted)")
    print("  - Missing inputs: FS=None, flagged in missing_inputs list")
    print("  - Punjirimattom hexes: no silent default when Phase 3 missing")
    print("  - Phase 1 GWETROOT: real data readable and in valid [0,1] range")
    print("  - Worst-case params always produce lower FS than best-case params")
    print("=" * 65)
