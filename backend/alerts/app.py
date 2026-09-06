"""
backend/alerts/app.py — Phase 11
Minimal FastAPI app mounting the Phase 11 alert router.

Dev entry point:
  uvicorn backend.alerts.app:app --port 8002 --reload

When Guhan-10's Phase 8 backend is ready, he imports and includes this router
directly into the main app:
  from backend.alerts.router import router as alerts_router
  app.include_router(alerts_router)
No other changes required.
"""

import logging

from fastapi import FastAPI

from .router import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="HydraSense Alert API — Phase 11",
    description=(
        "CAP 1.2 alert generation, deduplication, and downgrade handling. "
        "SRS.md Sections 15, 17."
    ),
    version="0.1.0",
)

app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "phase": 11}
