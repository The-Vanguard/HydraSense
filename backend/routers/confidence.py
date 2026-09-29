"""
backend/routers/confidence.py
Confidence Breakdown API — Stage 5 (Final.md §13.4)

GET /confidence/{hex_id}/breakdown
  Returns the 3-factor confidence score breakdown for the hex tooltip.
  Reads the latest risk_scores row and recomputes the breakdown with
  the empirical C_cal from LORO (Stage 4).

GET /confidence/{hex_id}/persistent
  Returns the current Persistent Threat state for a hex.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, HTTPException

from backend.database import get_db
from backend.alerts.persistent_threat import get_threat_state
from ml.models.train_fusion_model import compute_confidence_breakdown, _load_c_cal_uncalibrated
from backend import confidence as cf4
from ml.models.factor_of_safety import widen_fs_band

router = APIRouter(prefix="/confidence", tags=["confidence"])


@router.get("/{hex_id}/breakdown")
def confidence_breakdown(hex_id: str):
    """
    GET /confidence/{hex_id}/breakdown
    3-factor confidence breakdown for the hex tooltip (Final.md §13.4).

    Returns:
      model_probability_factor  — P_class × 100
      fs_band_penalty           — (FS_max - FS_min) / FS_max, clipped [0, 0.95]
      fs_uncertainty_factor     — 100 × (1 - penalty)
      has_local_calibration     — bool
      c_cal                     — LORO-empirical (1.0) or 1.0 for calibrated
      c_cal_source              — "loro_empirical" | "calibrated_region"
      confidence_score          — final composite [0–100]
    """
    with get_db() as conn:
        # Latest risk score row for this hex
        row = conn.execute(
            "SELECT risk_score, tier, confidence_score, feature_contributions "
            "FROM risk_scores WHERE hex_id = ? ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404,
                                detail="No risk scores found for hex_id=%s" % hex_id)

        # Static features for calibration flag + FS parameters
        hex_row = conn.execute(
            "SELECT static_features FROM hexes WHERE hex_id = ?", (hex_id,)
        ).fetchone()
        static: dict = {}
        if hex_row:
            try:
                static = json.loads(hex_row["static_features"] or "{}")
            except Exception:
                static = {}

    has_cal = bool(static.get("has_local_calibration", False))

    # Reconstruct FS band penalty from stored static features
    fs_val = static.get("factor_of_safety")
    fs_min = static.get("factor_of_safety_min")
    fs_max = static.get("factor_of_safety_max")

    # If we have min/max, compute raw penalty; else default 0 (no penalty)
    if fs_min is not None and fs_max is not None and fs_max > 0:
        raw_penalty = (float(fs_max) - float(fs_min)) / float(fs_max)
        fs_band_penalty = min(0.95, max(0.0, raw_penalty))
    else:
        fs_band_penalty = 0.0

    # P_class: derive from confidence_score and tier probability
    # Approximate P_class from stored confidence_score + c_cal back-calculation
    # (exact P_class not stored; use stored confidence as proxy divided by (1-penalty)*c_cal)
    # For the breakdown, c_cal is loaded from LORO in compute_confidence_breakdown.
    stored_conf = float(row["confidence_score"])
    # Approximate P_class: conf / (100 * (1-fs_penalty) * c_cal)
    # Use 0.5 as a safe default for P_class if we can't reconstruct it
    denom = 100.0 * (1.0 - fs_band_penalty)
    if denom > 0:
        p_class = min(1.0, max(0.0, stored_conf / denom))
    else:
        p_class = 0.5

    bd = compute_confidence_breakdown(
        model_class_probability = p_class,
        fs_band_width_penalty   = fs_band_penalty,
        has_local_calibration   = has_cal,
        # c_cal_uncalibrated=None -> loaded from LORO summary
    )

    return {
        **bd,
        "hex_id":          hex_id,
        "stored_risk_score":    row["risk_score"],
        "stored_tier":          row["tier"],
        "stored_confidence":    row["confidence_score"],
        "reference": "HydraSense_Final.md §13.4",
    }


_DATA_SOURCE_LAYER = cf4.RAIN_SOURCE_LAYER      # shared mapping, defined next to C_in


@router.get("/{hex_id}/factors")
def confidence_factors(hex_id: str):
    """
    GET /confidence/{hex_id}/factors
    v2 four-factor confidence (Sec. 9.2) with reasons (Sec. 13.3):
      100 x P_class x (1 - Eng_penalty) x C_cal x C_in

    Honest about what is reconstructed (see `assumptions`):
      * P_class is not stored, so it is inverted from the stored 3-factor confidence.
      * Only the rainfall data_source is stored; the soil layer is assumed to share its tier
        unless the hex is sensor_adjusted (then soil is a local sensor).
      * With no FS band stored, the engine penalty is the worst case (0.6), not a default.
      * C_cal uses the provisional 0.75 (the LORO-derived 1.0 is not trusted: that run had no
        negative samples).  All constants are provisional until the Sec. 15.6 fit.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT risk_score, tier, confidence_score, data_source, sensor_adjusted "
            "FROM risk_scores WHERE hex_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
            (hex_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"No risk scores found for hex_id={hex_id}")
        hex_row = conn.execute("SELECT static_features FROM hexes WHERE hex_id = ?", (hex_id,)).fetchone()
    try:
        static = json.loads((hex_row["static_features"] if hex_row else "{}") or "{}")
    except Exception:
        static = {}
    has_cal = bool(static.get("has_local_calibration", False))
    assumptions = []

    # -- P_class: invert the stored (old, 3-factor) confidence exactly as it was computed
    fs_min, fs_max = static.get("factor_of_safety_min"), static.get("factor_of_safety_max")
    old_pen = 0.0
    if fs_min is not None and fs_max is not None and float(fs_max) > 0:
        old_pen = min(0.95, max(0.0, (float(fs_max) - float(fs_min)) / float(fs_max)))
    old_c_cal = 1.0 if has_cal else _load_c_cal_uncalibrated()
    denom = 100.0 * (1.0 - old_pen) * old_c_cal
    p_class = min(1.0, max(0.0, float(row["confidence_score"]) / denom)) if denom > 0 else 0.0
    assumptions.append("P_class reconstructed from stored 3-factor confidence (not stored directly)")

    # -- engine penalty (v2 definition): needs the FS p05 / p50 / p95 band
    fs = static.get("factor_of_safety")
    if fs is not None and fs_min is not None and fs_max is not None:
        eng = cf4.fs_penalty(float(fs_min), float(fs), float(fs_max), has_cal)
        eng_src = "fs_band(min/fs/max used as p05/p50/p95)"
    else:
        eng = cf4.ENG_PENALTY_CAP
        eng_src = "unknown (no FS band stored): worst case"
        assumptions.append("no FS band stored for this hex: engine penalty set to the 0.6 worst case")

    # -- input layers
    rain = _DATA_SOURCE_LAYER.get(row["data_source"])
    if rain is None:
        rain = {"tier": None, "coverage": ""}
        assumptions.append(f"unrecognised data_source '{row['data_source']}': input coverage treated as unknown")
    soil = {"tier": 0, "coverage": "point"} if row["sensor_adjusted"] else dict(rain)
    if not row["sensor_adjusted"]:
        assumptions.append("soil layer assumed to have the same source tier as rainfall")
    out = cf4.compute_confidence(p_class, eng, has_cal, {"rainfall": rain, "soil": soil})
    return dict(
        hex_id=hex_id, stored_risk_score=row["risk_score"], stored_tier=row["tier"],
        stored_confidence_3factor=row["confidence_score"], engine_uncertainty_source=eng_src,
        p_class_source="reconstructed_from_stored_confidence", assumptions=assumptions,
        confidence_short_word=cf4.confidence_band(out["confidence_score"]),
        **out, reference="HydraSense_v2 Sec. 9.2, 13.3")


@router.get("/{hex_id}/persistent")
def persistent_threat(hex_id: str):
    """
    GET /confidence/{hex_id}/persistent
    Returns Persistent Threat state: cycles, declared, declared_at (Final.md §17.3).
    """
    state = get_threat_state(hex_id)
    return {
        **state,
        "threshold_cycles": 2,
        "reference": "HydraSense_Final.md §17.3",
    }
