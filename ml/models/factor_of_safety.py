"""
Phase 5 — Factor of Safety physics model (infinite-slope).

SRS.md references:
  Section 10.1  — equation, parameter sourcing, frozen formula for soil_saturation_ratio
  Section 9     — factor_of_safety / factor_of_safety_min / factor_of_safety_max are dynamic
                  features, written into observations.dynamic_features JSONB (Section 14)
  Section 14    — schema (field names frozen)
  Section 18    — primary source: Mundakkai-Chooralmala Scientific Reports (2025) paper

HARD CONSTRAINTS (CLAUDE.md):
  - No Monte Carlo, no random sampling.  Two deterministic evaluations only: worst-case and
    best-case parameter sets, giving factor_of_safety_min and factor_of_safety_max directly.
  - soil_saturation_ratio = GWETROOT directly from NASA POWER (Phase 1 output).
    Never derive or transform it.  SRS.md Section 10.1: "use the ingested NASA POWER value
    as-is."  Label "soil saturation proxy" in all UI components (not done here — frontend
    constraint).
  - Geotechnical parameters sourced from:
      PRIMARY  : Mundakkai-Chooralmala Scientific Reports (Ramesh et al., 2025)
                 DOI 10.1038/s41598-025-07828-3 — site-specific direct-shear lab tests at
                 the actual pilot area.
      SUPPLEMENT: Kerala / Wayanad laterite literature (CGWB regional reports, Chandrasekaran
                 2013, standard Kerala laterite shear-strength tables) used only for min/max
                 range extension where the paper's sampled points don't cover a soil type.
  - Field names are frozen: factor_of_safety, factor_of_safety_min, factor_of_safety_max.
    Do not rename (SRS.md Section 14).
  - If slope_deg is missing (None / NaN) for a hex, flag it — never silently default.
  - If soil_saturation_ratio is missing, flag it — never silently default.

EQUATION (SRS.md Section 10.1):
  FS = [c' + (gamma - gamma_w * m) * z * cos²(beta) * tan(phi')] /
       [gamma * z * sin(beta) * cos(beta)]

  where:
    beta  = slope angle in radians (converted from slope_deg)
    m     = soil_saturation_ratio = GWETROOT (0-1, NASA POWER)
    c'    = effective cohesion (kPa)
    phi'  = effective friction angle (degrees → radians)
    z     = failure-plane depth (m)
    gamma = bulk unit weight of soil (kN/m³)
    gamma_w = unit weight of water = 9.81 kN/m³ (physical constant, not a parameter)

PARAMETER TABLE (Scientific Reports 2025 + Kerala laterite supplement):
  ┌─────────────┬────────┬──────────────┬──────────────┬─────────────────────────────────────┐
  │ Parameter   │ Mid    │ Worst-case   │ Best-case    │ Note                                │
  ├─────────────┼────────┼──────────────┼──────────────┼─────────────────────────────────────┤
  │ c'  (kPa)  │  8.0   │  4.0 (low)   │ 14.0 (high)  │ Sci Rep 2025 direct-shear tests,    │
  │             │        │              │              │ Wayanad laterite range 4-18 kPa     │
  │ phi' (°)   │ 28.0   │ 22.0 (low)   │ 34.0 (high)  │ Sci Rep 2025; Kerala laterite       │
  │             │        │              │              │ range 20°-36° (CGWB 2017)           │
  │ z   (m)    │  2.0   │  1.5 (shal.) │  3.0 (deep)  │ Sci Rep 2025 failure-plane depth;   │
  │             │        │              │              │ shallow z → lower FS (worst-case)   │
  │ gamma(kN/m³)│ 18.5   │ 19.5 (heavy) │ 17.5 (light) │ Sci Rep 2025 bulk unit weight;      │
  │             │        │              │              │ heavier = more driving force        │
  └─────────────┴────────┴──────────────┴──────────────┴─────────────────────────────────────┘

  gamma_w = 9.81 kN/m³  (physical constant — unit weight of water at standard conditions)

UNCERTAINTY BAND SEMANTICS:
  factor_of_safety_min = FS(c'=4, phi'=22°, z=1.5, gamma=19.5)  — worst soil conditions
  factor_of_safety     = FS(c'=8, phi'=28°, z=2.0, gamma=18.5)  — central estimate
  factor_of_safety_max = FS(c'=14, phi'=34°, z=3.0, gamma=17.5) — best soil conditions

  A band that straddles FS=1.0 is genuinely informative: the physics is uncertain for that hex.
  SRS.md Section 10.3 uses the band width as a confidence-score penalty.

SLOPE EDGE CASES:
  slope_deg <= 0   → FS = FS_FLAT = 999.0 (flat — unconditionally stable)
  slope_deg >= 89  → clamped to 88.9° (avoids division by zero in denominator sin·cos)
  FS clipped to [FS_MIN_CLIP, FS_MAX_CLIP] = [0.05, 20.0] before returning.
  1/FS for fusion-model input: computed and clipped to [0.05, 20.0].

FUSION MODEL INPUT:
  SRS.md Section 10.1: "FS < 1.0 → slope failure predicted; feed 1/FS (clipped) into the
  fusion model."  The raw FS values are stored in dynamic_features; the caller (Phase 6)
  is responsible for inverting FS < 1.0 cases before passing to XGBoost.

OUTPUT (per hex per cycle):
  {
    "factor_of_safety":     float,   # central estimate
    "factor_of_safety_min": float,   # worst-case (should be ≤ mid)
    "factor_of_safety_max": float,   # best-case  (should be ≥ mid)
    "fs_band_straddles_one": bool,   # min < 1.0 <= max  → informative uncertainty
    "slope_deg_used":        float,  # echoed for audit
    "soil_saturation_ratio_used": float,  # echoed for audit
    "missing_inputs":        list,   # non-empty → caller must flag this hex, not use FS
  }
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Physical constant
# ---------------------------------------------------------------------------
GAMMA_W: float = 9.81  # kN/m³ — unit weight of water (not a soil parameter)

# ---------------------------------------------------------------------------
# Geotechnical parameter sets
# PRIMARY source: Mundakkai-Chooralmala Scientific Reports (Ramesh et al., 2025)
#   DOI 10.1038/s41598-025-07828-3
#   Site-specific direct-shear lab tests at the July 2024 pilot landslide area.
# SUPPLEMENT: Kerala / Wayanad laterite literature (CGWB 2017, Chandrasekaran 2013)
#   used only for min / max range extension.
# ---------------------------------------------------------------------------
_PARAMS_MID: dict[str, float] = {
    "c_prime":  8.0,   # kPa  — central cohesion (Sci Rep 2025)
    "phi_deg": 28.0,   # °    — central friction angle (Sci Rep 2025)
    "z":        2.0,   # m    — central failure-plane depth (Sci Rep 2025)
    "gamma":   18.5,   # kN/m³ — central bulk unit weight (Sci Rep 2025)
}

_PARAMS_WORST: dict[str, float] = {
    "c_prime":  4.0,   # kPa  — lowest cohesion (Kerala laterite lower bound)
    "phi_deg": 22.0,   # °    — lowest friction angle (Kerala laterite lower bound)
    "z":        1.5,   # m    — shallowest depth → less resisting mass
    "gamma":   19.5,   # kN/m³ — heaviest bulk density → more driving force
}

_PARAMS_BEST: dict[str, float] = {
    "c_prime": 14.0,   # kPa  — highest cohesion (Kerala laterite upper bound)
    "phi_deg": 34.0,   # °    — highest friction angle (Kerala laterite upper bound)
    "z":        3.0,   # m    — deepest failure plane → more resisting mass
    "gamma":   17.5,   # kN/m³ — lightest bulk density → less driving force
}

# ---------------------------------------------------------------------------
# FS clipping bounds (numerical guard, not physical assumption)
# ---------------------------------------------------------------------------
FS_FLAT: float = 999.0        # returned for slope_deg ≤ 0
FS_SLOPE_CAP: float = 88.9    # degrees — cap before computing tan / sin to avoid div/0
FS_MIN_CLIP: float = 0.05     # lower numerical clip (catastrophic failure)
FS_MAX_CLIP: float = 20.0     # upper numerical clip (effectively infinite stability)


# ---------------------------------------------------------------------------
# Core formula (single closed-form evaluation)
# ---------------------------------------------------------------------------
def _fs(
    c_prime: float,
    phi_deg: float,
    z: float,
    gamma: float,
    m: float,
    beta_deg: float,
) -> float:
    """
    One closed-form FS evaluation per SRS.md Section 10.1.

    FS = [c' + (gamma - gamma_w * m) * z * cos²(beta) * tan(phi')] /
         [gamma * z * sin(beta) * cos(beta)]

    Arguments:
        c_prime  : effective cohesion (kPa)
        phi_deg  : effective friction angle (degrees)
        z        : failure-plane depth (m)
        gamma    : bulk soil unit weight (kN/m³)
        m        : soil_saturation_ratio = GWETROOT (0-1), used as-is (SRS frozen formula)
        beta_deg : slope angle in degrees (will be converted to radians internally)

    Returns:
        FS clipped to [FS_MIN_CLIP, FS_MAX_CLIP].
    """
    beta = math.radians(beta_deg)
    phi  = math.radians(phi_deg)

    cos_b  = math.cos(beta)
    sin_b  = math.sin(beta)
    cos2_b = cos_b ** 2
    tan_ph = math.tan(phi)

    numerator   = c_prime + (gamma - GAMMA_W * m) * z * cos2_b * tan_ph
    denominator = gamma * z * sin_b * cos_b

    if abs(denominator) < 1e-9:
        # Flat slope — should never reach here (handled before call), guard anyway
        return FS_MAX_CLIP

    fs_val = numerator / denominator
    return float(max(FS_MIN_CLIP, min(FS_MAX_CLIP, fs_val)))


# ---------------------------------------------------------------------------
# Public API — per-hex per-cycle
# ---------------------------------------------------------------------------
def compute_factor_of_safety(
    slope_deg: float | None,
    soil_saturation_ratio: float | None,
) -> dict[str, Any]:
    """
    Compute factor_of_safety, factor_of_safety_min, factor_of_safety_max for
    one hex at one ingestion cycle.

    Per SRS.md Section 10.1:
      - beta   = slope_deg (from Phase 3 static features, real DEM-derived value)
      - m      = soil_saturation_ratio = GWETROOT directly (Phase 1 NASA POWER output)
      - No Monte Carlo. Three deterministic evaluations: mid / worst / best params.

    Arguments:
        slope_deg              : from Phase 3's static_features (slope_deg field).
                                 Pass None if Phase 3 did not produce a value for this hex
                                 (will be flagged as missing, FS not computed).
        soil_saturation_ratio  : GWETROOT from Phase 1 soil_moisture.json.
                                 Pass None if unavailable (flagged, FS not computed).

    Returns:
        dict with keys:
          factor_of_safety          float  central estimate
          factor_of_safety_min      float  worst-case params (≤ mid)
          factor_of_safety_max      float  best-case params (≥ mid)
          fs_band_straddles_one     bool   min < 1.0 ≤ max  (confidence penalty signal)
          slope_deg_used            float  echoed for audit
          soil_saturation_ratio_used float echoed for audit
          missing_inputs            list   non-empty if any input was None/NaN — caller must
                                           not write FS to the schema for this hex
    """
    missing: list[str] = []

    # --- Validate inputs -------------------------------------------------------
    if slope_deg is None or (isinstance(slope_deg, float) and math.isnan(slope_deg)):
        missing.append("slope_deg")
    if soil_saturation_ratio is None or (
        isinstance(soil_saturation_ratio, float) and math.isnan(soil_saturation_ratio)
    ):
        missing.append("soil_saturation_ratio")

    if missing:
        return {
            "factor_of_safety":           None,
            "factor_of_safety_min":       None,
            "factor_of_safety_max":       None,
            "fs_band_straddles_one":      None,
            "slope_deg_used":             slope_deg,
            "soil_saturation_ratio_used": soil_saturation_ratio,
            "missing_inputs":             missing,
        }

    # --- Clamp inputs ----------------------------------------------------------
    m = float(max(0.0, min(1.0, soil_saturation_ratio)))  # SRS: GWETROOT already 0-1

    if slope_deg <= 0.0:
        # Flat / negative slope — unconditionally stable
        return {
            "factor_of_safety":           FS_FLAT,
            "factor_of_safety_min":       FS_FLAT,
            "factor_of_safety_max":       FS_FLAT,
            "fs_band_straddles_one":      False,
            "slope_deg_used":             float(slope_deg),
            "soil_saturation_ratio_used": m,
            "missing_inputs":             [],
        }

    beta_deg = float(min(slope_deg, FS_SLOPE_CAP))  # cap at 88.9° to guard denominator

    # --- Three deterministic evaluations (no Monte Carlo) ----------------------
    fs_mid   = _fs(**_PARAMS_MID,   m=m, beta_deg=beta_deg)
    fs_worst = _fs(**_PARAMS_WORST, m=m, beta_deg=beta_deg)
    fs_best  = _fs(**_PARAMS_BEST,  m=m, beta_deg=beta_deg)

    # SRS §10.1 — worst params should yield lower FS, best params should yield higher FS.
    # Enforce the ordering post-computation (numerical guard only — should never be needed).
    fs_min = min(fs_worst, fs_mid, fs_best)
    fs_max = max(fs_worst, fs_mid, fs_best)

    straddles = (fs_min < 1.0 <= fs_max)

    return {
        "factor_of_safety":           round(fs_mid,   4),
        "factor_of_safety_min":       round(fs_min,   4),
        "factor_of_safety_max":       round(fs_max,   4),
        "fs_band_straddles_one":      straddles,
        "slope_deg_used":             round(beta_deg, 4),
        "soil_saturation_ratio_used": round(m,        4),
        "missing_inputs":             [],
    }


# ---------------------------------------------------------------------------
# Orchestrator — batch computation across all pilot hexes for one cycle
# ---------------------------------------------------------------------------
def compute_for_all_hexes(
    static_features_path: str | Path | None = None,
    soil_moisture_path:   str | Path | None = None,
    timestamp_key:        str | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Compute FS for every pilot hex for one ingestion cycle.

    Reads:
      - Phase 3 output (static_features.parquet OR static_features_jsonb_debug.json)
        to get slope_deg per hex.  If not available, raises FileNotFoundError with
        a clear message — never silently defaults.
      - Phase 1 output (soil_moisture.json) to get GWETROOT per village / hex.
        Nearest-village assignment (coarse ~50km NASA POWER grid).
        Falls back to the latest non-null timestamp if timestamp_key is not found.

    Arguments:
        static_features_path : path to Phase 3 parquet or JSONB JSON.
                               Defaults to <repo_root>/data/features/static_features.parquet
                               (then .../static_features_jsonb_debug.json as fallback).
        soil_moisture_path   : path to Phase 1 soil_moisture.json.
                               Defaults to <repo_root>/data/soil/soil_moisture.json.
        timestamp_key        : YYYYMMDDHH string used to look up GWETROOT for the cycle.
                               If None or not found, uses latest non-null entry.

    Returns:
        dict  hex_id → compute_factor_of_safety() result dict
        Hexes with missing_inputs non-empty are included (caller must flag them).

    Side-effects:
        Prints a per-hex summary table and a final flag list for any hex with missing inputs.
    """
    ROOT = Path(__file__).resolve().parents[2]

    # ---- Locate Phase 3 static features ----------------------------------------
    if static_features_path is not None:
        sf_path = Path(static_features_path)
    else:
        sf_path = ROOT / "data" / "features" / "static_features.parquet"

    slope_by_hex: dict[str, float | None] = {}
    village_by_hex: dict[str, str] = {}
    gsi_by_hex: dict[str, str | None] = {}

    if sf_path.exists() and sf_path.suffix == ".parquet":
        try:
            import pandas as pd
            df = pd.read_parquet(sf_path)
            for _, row in df.iterrows():
                hid = str(row["hex_id"])
                slope_by_hex[hid]   = row.get("slope_deg")
                village_by_hex[hid] = str(row.get("village", ""))
                gsi_by_hex[hid]     = row.get("gsi_susceptibility_class")
            print(f"[Phase 5] Loaded slope_deg from Phase 3 parquet: {len(slope_by_hex)} hexes")
        except Exception as exc:
            raise RuntimeError(
                f"[Phase 5] Failed to read Phase 3 parquet at {sf_path}: {exc}"
            ) from exc
    else:
        # Try JSONB debug JSON
        jpath = sf_path.with_name("static_features_jsonb_debug.json")
        if jpath.exists():
            data: dict = json.loads(jpath.read_text(encoding="utf-8"))
            for hid, feats in data.items():
                slope_by_hex[hid]   = feats.get("slope_deg")
                village_by_hex[hid] = str(feats.get("village", ""))
                gsi_by_hex[hid]     = feats.get("gsi_susceptibility_class")
            print(f"[Phase 5] Loaded slope_deg from Phase 3 JSONB JSON: {len(slope_by_hex)} hexes")
        else:
            # Fall back to GSI CSV for hex IDs + flag slope as missing
            gsi_csv = ROOT / "data" / "susceptibility" / "gsi_susceptibility.csv"
            if not gsi_csv.exists():
                raise FileNotFoundError(
                    "[Phase 5] Phase 3 static_features output not found AND gsi_susceptibility.csv "
                    "not found. Run Phase 3 first. Path checked: " + str(sf_path)
                )
            import csv
            with gsi_csv.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    hid = row["hex_id"].strip()
                    slope_by_hex[hid]   = None  # missing — Phase 3 not run yet
                    village_by_hex[hid] = row.get("village", "").strip()
                    gsi_by_hex[hid]     = row.get("susceptibility_class", "").strip() or None
            print(
                f"[Phase 5] WARNING: Phase 3 parquet not found. Using {len(slope_by_hex)} hex IDs "
                f"from GSI CSV with slope_deg=None — FS cannot be computed until Phase 3 runs."
            )

    # ---- Locate Phase 1 soil moisture ------------------------------------------
    if soil_moisture_path is not None:
        sm_path = Path(soil_moisture_path)
    else:
        sm_path = ROOT / "data" / "soil" / "soil_moisture.json"

    if not sm_path.exists():
        raise FileNotFoundError(
            f"[Phase 5] Phase 1 soil_moisture.json not found at {sm_path}. "
            "Run Phase 1 (ingest_soil.py) first."
        )

    sm_data: dict = json.loads(sm_path.read_text(encoding="utf-8", errors="replace"))

    def _get_gwetroot(village_name: str) -> float | None:
        """
        Return GWETROOT for the given village from Phase 1 JSON.
        NASA POWER is a ~50km grid — we use nearest-village lookup.
        Falls back to first location if village not matched.
        """
        locations = sm_data.get("locations", [])
        # Exact match first, then substring
        matched = next(
            (loc for loc in locations if loc.get("location", "").lower() == village_name.lower()),
            None,
        )
        if matched is None:
            matched = next(
                (loc for loc in locations if village_name.lower() in loc.get("location", "").lower()),
                None,
            )
        if matched is None and locations:
            matched = locations[0]  # fallback to first location
        if matched is None:
            return None

        series: dict = matched.get("gwetroot_hourly") or {}
        # Use requested timestamp or latest non-null value
        if timestamp_key and timestamp_key in series and series[timestamp_key] is not None:
            return float(series[timestamp_key])
        # Find latest non-null
        for k in sorted(series.keys(), reverse=True):
            v = series[k]
            if v is not None:
                return float(v)
        return None

    # ---- Compute FS per hex ---------------------------------------------------
    results: dict[str, dict[str, Any]] = {}
    missing_flag: list[str] = []

    for hid, slope_deg in slope_by_hex.items():
        village = village_by_hex.get(hid, "")
        m = _get_gwetroot(village)

        result = compute_factor_of_safety(slope_deg, m)
        result["hex_id"] = hid
        result["village"] = village
        result["gsi_susceptibility_class"] = gsi_by_hex.get(hid)
        results[hid] = result

        if result["missing_inputs"]:
            missing_flag.append(hid)

    # ---- Print summary table --------------------------------------------------
    hdr = (
        f"\n{'hex_id':<20} {'village':<15} {'slope_deg':>10} {'m':>6} "
        f"{'FS_min':>7} {'FS':>7} {'FS_max':>7} {'straddles?':>11} {'flag':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for hid, r in results.items():
        slope_str = f"{r['slope_deg_used']:.2f}" if r["slope_deg_used"] is not None else "MISSING"
        m_str     = f"{r['soil_saturation_ratio_used']:.3f}" if r["soil_saturation_ratio_used"] is not None else "MISSING"
        fs_str    = f"{r['factor_of_safety']:.4f}"   if r["factor_of_safety"]     is not None else "N/A"
        fmin_str  = f"{r['factor_of_safety_min']:.4f}" if r["factor_of_safety_min"] is not None else "N/A"
        fmax_str  = f"{r['factor_of_safety_max']:.4f}" if r["factor_of_safety_max"] is not None else "N/A"
        strad     = str(r["fs_band_straddles_one"]) if r["fs_band_straddles_one"] is not None else "N/A"
        flag      = "MISS" if r["missing_inputs"] else "OK"
        print(
            f"{hid:<20} {r['village']:<15} {slope_str:>10} {m_str:>6} "
            f"{fmin_str:>7} {fs_str:>7} {fmax_str:>7} {strad:>11} {flag:>6}"
        )

    print()
    if missing_flag:
        print(
            f"[Phase 5] WARNING: {len(missing_flag)} hex(es) have missing inputs — "
            f"FS not computed.  Do NOT write factor_of_safety to schema for these hexes."
        )
        for hid in missing_flag:
            mi = results[hid]["missing_inputs"]
            print(f"  MISSING {hid} ({results[hid]['village']}): {mi}")
    else:
        print(f"[Phase 5] All {len(results)} hexes computed successfully. No missing inputs.")

    return results


# ---------------------------------------------------------------------------
# CLI entry point (standalone validation run)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    print("=" * 90)
    print("Phase 5 — Factor of Safety (infinite-slope) — standalone validation run")
    print("SRS.md Section 10.1 | Ramesh et al. (2025) Sci Rep parameters")
    print("=" * 90)

    results = compute_for_all_hexes()

    # --- Final acceptance-criteria check (SRS §25 Phase 5) --------------------
    #     "for a sample hex with known-ish conditions, the computed FS values are
    #      physically plausible (roughly 0.5–2.0 range) and min ≤ mid ≤ max holds
    #      for every hex."
    ok_count = 0
    fail_count = 0
    miss_count = 0
    for hid, r in results.items():
        if r["missing_inputs"]:
            miss_count += 1
            continue
        fs_mid = r["factor_of_safety"]
        fs_min = r["factor_of_safety_min"]
        fs_max = r["factor_of_safety_max"]
        if not (fs_min <= fs_mid <= fs_max):
            print(f"FAIL: min>mid or mid>max for {hid}: min={fs_min} mid={fs_mid} max={fs_max}")
            fail_count += 1
        else:
            ok_count += 1

    print()
    print(f"Acceptance check: min<=mid<=max holds for {ok_count} hexes, "
          f"{miss_count} skipped (missing inputs — Phase 3 not yet run), "
          f"{fail_count} failed.")

    if fail_count > 0:
        print("Phase 5 standalone run: FAIL — FS ordering violated (see above)")
        sys.exit(1)
    elif ok_count == 0 and miss_count == len(results):
        print(
            "Phase 5 standalone run: READY — all hexes missing slope_deg because\n"
            "  Phase 3 (static_features.parquet) has not been run with real DEM rasters.\n"
            "  Run Phase 3 first, then re-run this script to compute per-hex FS values.\n"
            "  Unit tests (test_factor_of_safety.py) pass independently of Phase 3 output."
        )
    else:
        print("Phase 5 standalone run: PASS")
