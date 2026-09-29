"""
backend/physics_risk.py -- physics-first hazard index (the v2 Sec. 15.10 fallback headline).

WHY THIS EXISTS.  The deployed fusion model (ml/models/fusion_model.pkl) returns one constant score
for every hex (risk 58.23, driven only by `iot_anomaly_flag`), and event-held-out validation shows
XGBoost adds nothing over a single rain feature (docs: data/validation/baseline_v0*_results.json).
v2 Sec. 15.10 says that in that case the honest headline is a physics-first, uncertainty-aware
system with ML reported as an ablation.  This module is that system's scoring function.

THE INDEX (hand-set, UNCALIBRATED -- an engineered index, not a probability):

  trigger  T  = min(1, R / 2),  R = max over durations D of  I_obs(D) / I_thr(D),
               I_thr(D) = 14.82 * D^-0.39  mm/h   (Caine 1980, published global threshold)
  landslide   S = 0.5 * slope_term + 0.5 * P(FS<1)     slope_term = clip((slope - 10) / 25, 0, 1)
              P(FS<1) from backend.engines.run_e2_landslide (infinite slope, Monte Carlo over soil
              parameters and depth) using the hex's own soil parameters and current saturation
              index_ls = 100 * S * (0.25 + 0.75 * T)
  flood       F = clip(1 - HAND / 30, 0, 1)             (height above nearest drainage, m)
              index_ff = 100 * F * (0.15 + 0.85 * T)
  risk_score  = max(index_ls, index_ff)                 (compound = higher of the two, v2 Sec. 8.2)

A dry day on a steep saturated slope can reach at most 25; only an exceeded rainfall threshold moves
it into Orange / Red.  Missing inputs are never defaulted: a missing trigger gives T = 0 and is
listed in `missing_inputs`, which also lowers the confidence.

Validated only as far as ml/dataset/eval_physics_risk.py shows (event-held-out AUC on the graded
event table); the cut points (30 / 55 / 75) are project defaults pending calibration (v2 Sec. 9.1).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

import numpy as np

from backend.confidence import ENG_PENALTY_CAP, compute_confidence, fs_penalty
from backend.engines import compute_id_threshold, run_e2_landslide

NAME = "physics_first_index_v0"
DESCRIPTION = ("Hand-set physics-first hazard index: rainfall-threshold trigger x (slope + P(FS<1)) for "
               "landslide, x HAND for flood. Uncalibrated engineered index, not a probability.")
TIERS = ((75.0, "Red"), (55.0, "Orange"), (30.0, "Yellow"), (0.0, "Green"))
TRIGGER_FLOOR_LS, TRIGGER_FLOOR_FF = 0.25, 0.15
DURATION_KEYS = {1: "rainfall_1h", 3: "rainfall_3h", 6: "rainfall_6h", 24: "rainfall_24h",
                 72: "rainfall_72h_antecedent"}
HAND_FULL_M = 30.0            # HAND at or above this: no flood susceptibility
SLOPE_LO, SLOPE_SPAN = 10.0, 25.0
CAVEATS = ["hand-set weights, not fitted", "uncalibrated: not a probability of an event",
           "Caine (1980) is a global threshold; reanalysis rain under-reads extreme storms",
           "P(FS<1) uses SoilGrids-derived parameters and a default depth when local ones are missing"]


def tier_from_score(score: float) -> str:
    for cut, tier in TIERS:
        if score >= cut:
            return tier
    return "Green"


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return None if (math.isnan(v)) else v
    except (TypeError, ValueError):
        return None


def rain_trigger(f: Mapping[str, Any]) -> tuple[Optional[float], Optional[int]]:
    """(R, controlling duration) -- the largest I_obs/I_thr over the durations with data."""
    best, best_d = None, None
    for d, key in DURATION_KEYS.items():
        mm = _num(f.get(key))
        if mm is None:
            continue
        r = compute_id_threshold(mm / d, d) if mm > 0 else 0.0
        if best is None or r > best:
            best, best_d = r, d
    return best, best_d


def score_features(f: Mapping[str, Any], seed: int = 0) -> dict:
    """Score one hex from a merged static+dynamic feature dict.  Deterministic for a given seed."""
    missing: list[str] = []
    slope = _num(f.get("slope_deg"))
    hand = _num(f.get("hand_m"))
    sat = _num(f.get("soil_saturation_ratio"))
    R, ctl = rain_trigger(f)
    if R is None:
        missing.append("rainfall")
        T = 0.0
    else:
        T = min(1.0, R / 2.0)
    if sat is None:
        missing.append("soil_saturation")

    # ---- landslide susceptibility
    slope_term = None if slope is None else float(np.clip((slope - SLOPE_LO) / SLOPE_SPAN, 0.0, 1.0))
    p_fs, fs_p50, fs_min, fs_max = None, None, None, None
    soil_ok = all(_num(f.get(k)) is not None for k in
                  ("soil_c_prime_kpa", "soil_phi_deg", "soil_z_m", "soil_gamma_kn_m3"))
    if slope is not None and soil_ok and sat is not None:
        np.random.seed(seed)                                  # the engine draws from the global RNG
        e2 = run_e2_landslide(
            slope_deg=slope, soil_depth_m=float(f["soil_z_m"]), cohesion_kpa=float(f["soil_c_prime_kpa"]),
            friction_angle_deg=float(f["soil_phi_deg"]), unit_weight_kn_m3=float(f["soil_gamma_kn_m3"]),
            saturation_ratio=float(np.clip(sat, 0.0, 1.0)),
            has_local_calibration=bool(f.get("has_local_calibration", False)), num_samples=400)
        p_fs, fs_p50 = e2["p_fs_less_than_1"], e2["factor_of_safety"]
        fs_min, fs_max = e2["factor_of_safety_min"], e2["factor_of_safety_max"]
    elif slope is not None and not soil_ok:
        missing.append("soil_parameters")
    if slope is None:
        missing.append("slope")
    parts = [x for x in (slope_term, p_fs) if x is not None]
    S = 0.0 if not parts else (0.5 * slope_term + 0.5 * p_fs if len(parts) == 2 else parts[0])
    ls_mult = TRIGGER_FLOOR_LS + (1 - TRIGGER_FLOOR_LS) * T
    index_ls = 100.0 * S * ls_mult

    # ---- flood susceptibility
    F = 0.0 if hand is None else float(np.clip(1.0 - hand / HAND_FULL_M, 0.0, 1.0))
    if hand is None:
        missing.append("hand_m")
    ff_mult = TRIGGER_FLOOR_FF + (1 - TRIGGER_FLOOR_FF) * T
    index_ff = 100.0 * F * ff_mult

    score = round(max(index_ls, index_ff), 4)
    hazard = "landslide" if index_ls >= index_ff else "flood"
    # additive attribution of the controlling index (drop-to-baseline for the trigger)
    if hazard == "landslide":
        base = 100.0 * S * TRIGGER_FLOOR_LS
        contrib = {"rain_trigger": index_ls - base}
        w_slope, w_fs = (0.5, 0.5) if len(parts) == 2 else (1.0 if slope_term is not None else 0.0,
                                                            1.0 if p_fs is not None else 0.0)
        tot = (w_slope * (slope_term or 0.0) + w_fs * (p_fs or 0.0)) or 1.0
        contrib["slope"] = base * (w_slope * (slope_term or 0.0)) / tot
        contrib["p_fs_lt1"] = base * (w_fs * (p_fs or 0.0)) / tot
    else:
        base = 100.0 * F * TRIGGER_FLOOR_FF
        contrib = {"rain_trigger": index_ff - base, "hand_m": base}
    return dict(
        risk_score=score, tier=tier_from_score(score), hazard=hazard, index_landslide=round(index_ls, 3),
        index_flood=round(index_ff, 3), trigger=round(T, 4), trigger_ratio=None if R is None else round(R, 4),
        controlling_duration_h=ctl, saturation=sat, slope_term=slope_term, p_fs_lt1=p_fs,
        factor_of_safety=fs_p50, factor_of_safety_min=fs_min, factor_of_safety_max=fs_max,
        flood_susceptibility=round(F, 4), missing_inputs=missing,
        feature_contributions={k: round(float(v), 4) for k, v in contrib.items()},
        method=NAME, caveats=CAVEATS)


def _tier_margin(score: float) -> float:
    """How far the score sits from the nearest tier edge, mapped to 0.5..1.0.  A stability
    indicator ('would a small change flip the tier?'), NOT a probability."""
    edges = [30.0, 55.0, 75.0]
    d = min(abs(score - e) for e in edges)
    return float(np.clip(0.5 + min(d, 20.0) / 40.0, 0.5, 1.0))


class PhysicsRiskModel:
    """Drop-in replacement for the FusionModel interface used by backend/risk_engine.py."""
    name = NAME

    def predict_one(self, features: Mapping[str, Any]) -> dict:
        out = score_features(features)
        layers = features.get("_input_layers") or {}
        has_cal = bool(features.get("has_local_calibration", False))
        fsmin, fsmax, fs50 = out["factor_of_safety_min"], out["factor_of_safety_max"], out["factor_of_safety"]
        eng = (fs_penalty(fsmin, fs50, fsmax, has_cal) if fs50 is not None else ENG_PENALTY_CAP)
        if out["missing_inputs"]:
            layers = {**layers, "missing": {"tier": 3, "coverage": "static"}}      # missing input => low C_in
        conf = compute_confidence(_tier_margin(out["risk_score"]), eng, has_cal, layers or {"none": {}})
        out["confidence_score"] = conf["confidence_score"]
        out["confidence_factors"] = conf["confidence_factors"]
        out["confidence_primary_reason"] = conf["primary_reason"]
        out["confidence_note"] = ("P_class here is a tier-margin stability indicator, not a model "
                                  "probability; the score is an engineered index")
        return out
