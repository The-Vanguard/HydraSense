"""
backend/routers/validation.py -- GET /validation/loeo (SRS.md Section 15).
Serves Phase 7 loeo_summary.json statically. Never recomputed live.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/validation", tags=["validation"])

LOEO_SUMMARY_PATH = ROOT / "data" / "validation" / "loeo_summary.json"
LOEO_RESULTS_PATH = ROOT / "data" / "validation" / "loeo_results.json"


@router.get("/loeo")
def get_loeo():
    """
    GET /validation/loeo -- aggregated LOEO results, served static (SRS.md Section 15).
    Populated by Phase 7 offline run. Never recomputed live on stage.
    """
    if not LOEO_SUMMARY_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="LOEO results not found. Run: python ml/validation/loeo.py"
        )
    try:
        summary = json.loads(LOEO_SUMMARY_PATH.read_text(encoding="utf-8"))
        results = []
        if LOEO_RESULTS_PATH.exists():
            results = json.loads(LOEO_RESULTS_PATH.read_text(encoding="utf-8"))
        return {"summary": summary, "per_event_results": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error reading LOEO results: {exc}")
