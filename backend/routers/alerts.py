"""
backend/routers/alerts.py -- Alert endpoints (SRS.md Section 15).
/alert/trigger and /alert/feed are Phase 11 (guru-elight).
Stubbed 501 so Phase 12 frontend can reference the route without breaking.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/alert", tags=["alerts"])


@router.post("/trigger")
def alert_trigger():
    """POST /alert/trigger -- Phase 11 (guru-elight). Not yet implemented."""
    return JSONResponse(
        status_code=501,
        content={
            "detail": "POST /alert/trigger is Phase 11 (guru-elight). Not yet implemented.",
            "phase": 11,
        }
    )


@router.get("/feed")
def alert_feed():
    """GET /alert/feed -- Phase 11 (guru-elight). Not yet implemented."""
    return JSONResponse(
        status_code=501,
        content={
            "detail": "GET /alert/feed is Phase 11 (guru-elight). Not yet implemented.",
            "phase": 11,
        }
    )
