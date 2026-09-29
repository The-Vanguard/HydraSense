"""
backend/routers/validation.py — GET /validation/loeo + /validation/loro (Final.md §16.3).
Serves Phase 7 (LOEO) and Stage 4 (LORO) results statically. Never recomputed live.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/validation", tags=["validation"])

LOEO_SUMMARY_PATH = ROOT / "data" / "validation" / "loeo_summary.json"
LOEO_RESULTS_PATH = ROOT / "data" / "validation" / "loeo_results.json"
LORO_SUMMARY_PATH = ROOT / "data" / "validation" / "loro_summary.json"
LORO_RESULTS_PATH = ROOT / "data" / "validation" / "loro_results.json"


def sanitize_nans(val):
    """Recursively replaces NaN and Inf floats with None (JSON null)."""
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    elif isinstance(val, dict):
        return {k: sanitize_nans(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_nans(v) for v in val]
    return val


@router.get("/loeo")
def get_loeo():
    """
    GET /validation/loeo — LOEO (Leave-One-Event-Out) results.
    Populated by: python ml/validation/loeo.py
    """
    if not LOEO_SUMMARY_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="LOEO results not found. Run: python ml/validation/loeo.py"
        )
    try:
        summary = sanitize_nans(json.loads(LOEO_SUMMARY_PATH.read_text(encoding="utf-8")))
        results = []
        if LOEO_RESULTS_PATH.exists():
            results = sanitize_nans(json.loads(LOEO_RESULTS_PATH.read_text(encoding="utf-8")))
        return {"summary": summary, "per_event_results": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error reading LOEO results: {exc}")


@router.get("/loro")
def get_loro():
    """
    GET /validation/loro — LORO (Leave-One-Region-Out) results (Final.md §16.3).
    Populated by: python ml/validation/loro.py
    """
    if not LORO_SUMMARY_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="LORO results not found. Run: python ml/validation/loro.py"
        )
    try:
        summary = sanitize_nans(json.loads(LORO_SUMMARY_PATH.read_text(encoding="utf-8")))
        results = []
        if LORO_RESULTS_PATH.exists():
            results = sanitize_nans(json.loads(LORO_RESULTS_PATH.read_text(encoding="utf-8")))
        warning = None
        fp = summary.get("false_positive_rate_aggregate")
        if fp is not None and float(fp) == 0.0:
            warning = ("This run has no negative (non-event) samples, so the detection rate is detection-only, "
                       "the 0% false-positive rate is not a measurement, and C_cal = 1.0 is not usable: the "
                       "system uses a provisional C_cal of 0.75. Event-held-out results on the graded events "
                       "are in data/validation/baseline_v0_results.json (landslide ROC-AUC about 0.55-0.66, "
                       "flash floods at chance).")
        return {
            "summary": summary,
            "reliability_warning": warning,
            "evidence_grade": "illustrative" if warning else "unassessed",
            "per_region_results": results,
            "methodology": "Leave-One-Region-Out: model trained on 9 regions, tested on held-out region.",
            "reference": "HydraSense_Final.md §16.3 / §11.3",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error reading LORO results: {exc}")


@router.get("/loro/c-cal/{region_code}")
def get_c_cal(region_code: str):
    """
    GET /validation/loro/c-cal/{region_code}
    Returns the empirical C_cal for a region from LORO results.
    Used by the confidence score breakdown tooltip (Final.md §13.4).
    """
    try:
        from ml.validation.loro import get_c_cal_for_region
        c_cal = get_c_cal_for_region(region_code)
        if isinstance(c_cal, float) and (math.isnan(c_cal) or math.isinf(c_cal)):
            c_cal = 0.75
        return {
            "region_code": region_code,
            "c_cal": c_cal,
            "source": "loro_empirical" if LORO_SUMMARY_PATH.exists() else "placeholder",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
