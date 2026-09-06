"""
backend/main.py -- HydraSense FastAPI application (Phase 8).

SRS.md Section 15 -- all endpoints implemented here.
Owner: Guhan-10

Run:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Endpoints:
    POST /ingest/rainfall
    POST /ingest/rainfall_forecast
    POST /ingest/soil_moisture
    POST /ingest/iot
    GET  /risk/{hex_id}
    GET  /risk/map
    GET  /risk/{hex_id}/history
    GET  /risk/{hex_id}/inundation   (gated: tier >= Orange in code)
    GET  /risk/{hex_id}/uncertainty
    GET  /validation/loeo
    GET  /shelters/nearest/{hex_id}
    POST /alert/trigger              (501 -- Phase 11)
    GET  /alert/feed                 (501 -- Phase 11)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routers import ingest, risk, validation, shelters, alerts
from backend.seed import run_seed

app = FastAPI(
    title="HydraSense Backend API",
    description="Real-time landslide early-warning system for Wayanad pilot cluster. SRS.md v1.",
    version="0.8.0",
)

# CORS open for frontend dashboard dev (Phase 12)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(risk.router)
app.include_router(validation.router)
app.include_router(shelters.router)
app.include_router(alerts.router)


@app.on_event("startup")
def startup():
    init_db()
    run_seed()
    print("[startup] HydraSense backend ready.")


@app.get("/", tags=["health"])
def health():
    return {
        "status": "ok",
        "service": "HydraSense Backend API",
        "phase": 8,
        "owner": "Guhan-10",
        "srs_section": "15",
    }
