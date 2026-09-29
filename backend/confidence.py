"""
backend/confidence.py -- v2 four-factor confidence (Sec. 9.2) with reasons (Sec. 13.3).

    Confidence = 100 x P_class x (1 - Eng_penalty) x C_cal x C_in

  P_class      the head's own class probability                              (statistical)
  Eng_penalty  engine-side uncertainty: FS band (landslide) or rainfall/CN/Tc (flood)
  C_cal        1.0 if the region has local calibration, else k < 1
  C_in         input coverage: how much of the live state is local observation vs
               satellite vs cached vs static  (NEW in v2; the old 3-factor code had no such term)

Everything here that is a *constant* is PROVISIONAL and is reported as such in every result
(`provisional_constants`).  v2 Sec. 9.2 / 15.6: k and the C_in levels must be fitted from
leave-one-region-out runs (bin raw confidence, compare with observed hit rate per data-
availability tier) before the displayed number can be said to track accuracy.  Until then this
is "a combined uncertainty and data-coverage indicator", never a probability of correctness.

Deliberate difference from ml/models/train_fusion_model.py: that module auto-loads
C_cal = 1.0 from data/validation/loro_summary.json.  The current LORO run has no negative
samples (false-positive rate 0.0, uncalibrated detection 1.0), so it cannot support a fitted C_cal
and using it would silently switch the calibration factor off.  Here the default is the
provisional 0.75 unless the caller passes a fitted value.

Pure functions; no database, no network.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

# ---------------------------------------------------------------------------
# Provisional constants (v2 Sec. 9.2, 7.2.2) -- to be fitted, see module docstring
# ---------------------------------------------------------------------------
C_CAL_UNCALIBRATED_DEFAULT = 0.75      # "k" in v2; illustrative in the worked example
ENG_PENALTY_CAP = 0.6                  # v2 Sec. 7.2.2
FS_BAND_WIDEN_W = 1.5                  # v2 Sec. 7.2.2, initial value, tuned in validation

# C_in level by (badge tier, coverage).  Badge tiers follow backend/rainfall.py:
#   0 = healthy local sensor, 1 = live regional observation, 2 = cached, 3 = static / terrain-only
# v2 text: 1.0 "with a healthy local sensor and gauge coverage; lower for satellite-only, cached
# or fallback tiers".  NOTE: v2's worked example shows C_in = 1.00 for satellite-live inputs,
# which contradicts that text; this module follows the text and flags the discrepancy.
C_IN_LEVELS = {
    (0, "point"): 1.00,
    (0, "gauge_merged"): 1.00,
    (1, "gauge_merged"): 0.95,
    (1, "satellite_only"): 0.85,
    (2, "gauge_merged"): 0.70,
    (2, "satellite_only"): 0.65,
    (3, "static"): 0.40,
}
C_IN_TIER_FALLBACK = {0: 1.00, 1: 0.85, 2: 0.65, 3: 0.40}
UNKNOWN_LAYER_LEVEL = 0.40             # a layer we know nothing about counts as static, never as good

PROVISIONAL_CONSTANTS = ("c_cal_uncalibrated", "c_in_levels", "eng_penalty_cap", "fs_band_widen_w")


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


# ---------------------------------------------------------------------------
# Engine penalties
# ---------------------------------------------------------------------------
def fs_penalty(fs_p05: float, fs_p50: float, fs_p95: float, has_local_calibration: bool = True,
               widen_w: float = FS_BAND_WIDEN_W) -> float:
    """
    Landslide Eng_penalty (v2 Sec. 7.2.2):  min(0.6, (p95 - p05) / (2 * p50)), multiplied by w
    when the region is uncalibrated, then capped again.  Returns 0..0.6.
    """
    if fs_p50 is None or fs_p50 <= 0 or fs_p05 is None or fs_p95 is None:
        return ENG_PENALTY_CAP                      # unknown band: worst case, never silence
    pen = min(ENG_PENALTY_CAP, max(0.0, (fs_p95 - fs_p05) / (2.0 * fs_p50)))
    if not has_local_calibration:
        pen = min(ENG_PENALTY_CAP, pen * widen_w)
    return pen


def flood_penalty(qp_low: float, qp_mid: float, qp_high: float) -> float:
    """
    Flood Eng_penalty: spread of peak discharge under plausible CN / Tc ranges, scaled to 0..0.6
    the same way as the FS band (v2 Sec. 9.2).  Returns 0..0.6; unknown -> worst case.
    """
    if qp_mid is None or qp_mid <= 0 or qp_low is None or qp_high is None:
        return ENG_PENALTY_CAP
    return min(ENG_PENALTY_CAP, max(0.0, (qp_high - qp_low) / (2.0 * qp_mid)))


# ---------------------------------------------------------------------------
# Input coverage  C_in
# ---------------------------------------------------------------------------
def _layer_fields(layer: Any) -> tuple[Optional[int], str]:
    if isinstance(layer, Mapping):
        return layer.get("tier"), str(layer.get("coverage", ""))
    return getattr(layer, "tier", None), str(getattr(layer, "coverage", ""))


def layer_level(layer: Any) -> float:
    tier, coverage = _layer_fields(layer)
    if tier is None:
        return UNKNOWN_LAYER_LEVEL
    return C_IN_LEVELS.get((int(tier), coverage), C_IN_TIER_FALLBACK.get(int(tier), UNKNOWN_LAYER_LEVEL))


def input_coverage(layers: Mapping[str, Any]) -> tuple[float, Optional[str], dict]:
    """
    C_in = the weakest dynamic layer's level (weakest-link: one stale input limits the whole
    estimate, and the limiting layer is nameable in the reason line).
    `layers`: {"rainfall": badge-or-dict, "soil": badge-or-dict, ...} with tier / coverage.
    Returns (c_in, limiting_layer, per_layer_levels).  No layers at all -> UNKNOWN level.
    """
    levels = {name: layer_level(b) for name, b in layers.items()}
    if not levels:
        return UNKNOWN_LAYER_LEVEL, None, {}
    limiting = min(levels, key=levels.get)
    return levels[limiting], limiting, levels


# ---------------------------------------------------------------------------
# Combined confidence with reasons
# ---------------------------------------------------------------------------
_REASON_TEXT = {
    "calibration": "no local historical calibration",
    "engine_uncertainty": "widened geotechnical uncertainty",
    "model_probability": "low model probability",
}


def _input_reason(layer: Optional[str], layers: Mapping[str, Any]) -> str:
    if layer is None:
        return "input coverage unknown"
    tier, coverage = _layer_fields(layers[layer])
    if tier == 2:
        return f"cached {layer} layer"
    if tier == 3:
        return f"{layer} layer on terrain/static estimate only"
    if coverage == "satellite_only":
        return f"satellite-only {layer}"
    return f"{layer} input not from a local sensor"


def compute_confidence(
    p_class: float,
    eng_penalty: float,
    has_local_calibration: bool,
    layers: Mapping[str, Any],
    c_cal_uncalibrated: Optional[float] = None,
    hazard: str = "landslide",
) -> dict:
    """
    Four-factor confidence with reasons.  `c_cal_uncalibrated` should be a FITTED value once
    Sec. 15.6 has been run; None uses the provisional default.
    """
    p = _clip(p_class)
    pen = _clip(eng_penalty, 0.0, ENG_PENALTY_CAP)
    cal_provisional = c_cal_uncalibrated is None
    k = C_CAL_UNCALIBRATED_DEFAULT if cal_provisional else _clip(c_cal_uncalibrated)
    c_cal = 1.0 if has_local_calibration else k
    c_in, limiting, levels = input_coverage(layers)

    score = round(100.0 * p * (1.0 - pen) * c_cal * c_in, 1)
    factors = {"model_probability": round(p * 100), "engine_uncertainty": round((1 - pen) * 100),
               "calibration": round(c_cal * 100), "input_coverage": round(c_in * 100)}

    # reasons: every factor that is below 100, largest shortfall first
    shortfall = {"model_probability": 1 - p, "engine_uncertainty": pen,
                 "calibration": 1 - c_cal, "input_coverage": 1 - c_in}
    reasons = []
    for name, gap in sorted(shortfall.items(), key=lambda kv: kv[1], reverse=True):
        if gap <= 0.005:
            continue
        text = _input_reason(limiting, layers) if name == "input_coverage" else _REASON_TEXT[name]
        reasons.append(dict(factor=name, shortfall_pct=round(gap * 100), text=text))

    return dict(
        hazard=hazard,
        confidence_score=score,
        confidence_factors=factors,
        primary_reason=reasons[0]["text"] if reasons else "all inputs local and calibrated",
        reasons=reasons,
        input_layer_levels={k_: round(v, 2) for k_, v in levels.items()},
        limiting_input_layer=limiting,
        has_local_calibration=has_local_calibration,
        c_cal_source="provisional_default" if (cal_provisional and not has_local_calibration)
                     else ("fitted" if not has_local_calibration else "calibrated_region"),
        provisional_constants=list(PROVISIONAL_CONSTANTS),
        label="combined uncertainty and data-coverage indicator (not a probability of correctness)",
    )


# data_source labels written by backend/rainfall.py -> (badge tier, coverage).  There are no rain gauges
# in the system, so live regional data is "satellite_only".
RAIN_SOURCE_LAYER = {
    "sensor":            {"tier": 0, "coverage": "point"},
    "live":              {"tier": 1, "coverage": "satellite_only"},
    "open_meteo_live":   {"tier": 1, "coverage": "satellite_only"},
    "imerg_cached":      {"tier": 2, "coverage": "satellite_only"},
    "open_meteo_cached": {"tier": 2, "coverage": "satellite_only"},
    "cached_demo":       {"tier": 2, "coverage": "satellite_only"},
}
SOIL_SOURCE_LAYER = {
    "sensor":           {"tier": 0, "coverage": "point"},
    "open_meteo":       {"tier": 1, "coverage": "satellite_only"},
    "model":            {"tier": 2, "coverage": "satellite_only"},
    "antecedent_index": {"tier": 3, "coverage": "static"},
}


def layers_from_sources(rain_source: Optional[str], soil_source: Optional[str],
                        sensor_adjusted: bool = False) -> dict:
    """Input layers for C_in from the source labels the pipeline records.  Unknown labels give a layer
    with no tier, which counts as UNKNOWN_LAYER_LEVEL (never as good)."""
    rain = RAIN_SOURCE_LAYER.get(rain_source or "", {"tier": None, "coverage": ""})
    soil = SOIL_SOURCE_LAYER.get(soil_source or "", {"tier": None, "coverage": ""})
    if sensor_adjusted:
        soil = SOIL_SOURCE_LAYER["sensor"]
    return {"rainfall": dict(rain), "soil": dict(soil)}


def confidence_band(score: float) -> str:
    """Word for the short Cell Broadcast template (v2 Sec. 10.5).  Cut points are provisional;
    they must be replaced by the fitted confidence bands (Sec. 9.2)."""
    return "high" if score >= 70 else ("medium" if score >= 45 else "low")
