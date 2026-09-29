"""
backend/main.py -- HydraSense FastAPI application.
Reference: HydraSense_Final.md §15.5 / §15.6 / §14.6 / §16.7

Run:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Endpoints (Stage 5/6/7 additions marked):
    GET  /                               health
    POST /region/resolve
    GET  /region/list
    GET  /region/{code}/hexes
    POST /ingest/rainfall
    POST /ingest/rainfall_forecast
    POST /ingest/soil_moisture
    POST /ingest/iot
    GET  /risk/{hex_id}
    GET  /risk/map
    GET  /risk/{hex_id}/history
    GET  /risk/{hex_id}/inundation       (gated: tier >= Orange)
    GET  /risk/{hex_id}/uncertainty
    GET  /confidence/{hex_id}/breakdown  §11.3 three-factor breakdown
    GET  /confidence/{hex_id}/persistent §17.3 persistent threat state
    GET  /validation/loeo
    GET  /validation/loro                §16.3 LORO results
    GET  /validation/loro/c-cal/{code}
    GET  /shelters/nearest/{hex_id}
    POST /alert/trigger
    GET  /alert/feed
    POST /alert/gate/approve             §12.4 two-person gate
    GET  /alert/gate/pending
    GET  /alert/gate/{hex_id}
    WS   /ws/alerts                      §15.6 real-time feed + reconnect snapshot
"""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import WebSocket, WebSocketDisconnect

from backend.database import init_db
from backend.routers import ingest, risk, validation, shelters, events, simulate
from backend.routers.region import router as region_router
from backend.routers.gate import router as gate_router
from backend.routers.confidence import router as confidence_router
from backend.routers.village import router as village_router
from backend.routers.evacuation import router as evacuation_router
from backend.alerts.router import router as alerts_router
from backend.alerts.websocket_manager import manager as ws_manager
from backend.seed import run_seed
from backend.seed_multiregion import run_seed_multiregion
from contextlib import asynccontextmanager
from backend.scheduler import lifespan as scheduler_lifespan  # §14.6 two loops


# ── Composite lifespan: DB/seed startup + scheduler loops (§14.6 / §15.7) ────
@asynccontextmanager
async def lifespan(app):
    """
    Composite FastAPI lifespan.

    On startup (before yield):
      1. init_db()          — ensures tables exist / runs schema migrations
      2. _migrate_db_schema_region()
      3. run_seed()         — seeds default region hexes
      4. run_seed_multiregion() — seeds all additional regions
      5. delegates to scheduler_lifespan for slow + fast loops

    On shutdown (after yield):
      scheduler_lifespan cancels the loops.

    Replaces the deprecated @app.on_event("startup") pattern (FastAPI ≥ 0.93).
    Reference: HydraSense_Final.md §15.5
    """
    # --- Startup tasks (formerly @app.on_event("startup")) ---
    init_db()
    _migrate_db_schema_region()
    run_seed()
    run_seed_multiregion()
    print("[startup] HydraSense backend ready — region-agnostic (Final.md §15.5).")
    print("[startup] APScheduler lifespan active — slow loop + fast IoT loop running.")
    print("[startup] Cold-start guard: active until first slow cycle completes.")

    # --- Hand off to scheduler lifespan (starts async loops, yields, cancels) ---
    async with scheduler_lifespan(app):
        yield


# ── FastAPI app with composite lifespan ───────────────────────────────────────
app = FastAPI(
    title="HydraSense Backend API",
    description="Region-agnostic flash-flood and landslide early-warning. HydraSense_Final.md.",
    version="2.0.0",
    lifespan=lifespan,   # composite: db/seed + slow/fast loops + cold-start guard
)

# CORS — open for frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(region_router)
app.include_router(ingest.router)
app.include_router(risk.router)
app.include_router(validation.router)
app.include_router(shelters.router)
app.include_router(alerts_router)
app.include_router(gate_router)
app.include_router(confidence_router)
app.include_router(village_router)
app.include_router(evacuation_router)
app.include_router(events.router)
app.include_router(simulate.router)


# ── WebSocket: reconnect-safe snapshot then delta push (§14.6) ───────────────
@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    """
    WS /ws/alerts — real-time stream (Final.md §15.6).

    On connect: immediately sends a full state snapshot of all hex tiers
    so a client that reconnects (e.g. after venue wifi drop) sees a
    consistent, fully-labeled map before any incremental delta arrives.
    This is §14.6's reconnect-safe requirement: 'always fetches a full
    state snapshot on connect or reconnect, before applying any incremental
    update on top.'
    """
    await ws_manager.connect(websocket)
    try:
        # Send snapshot immediately on connect
        try:
            from backend.routers.risk import _get_risk_map_data
            snapshot_hexes = _get_risk_map_data()
            await websocket.send_text(json.dumps({
                "type": "snapshot",
                "hexes": snapshot_hexes,
                "cold_start": _is_cold_start(),
            }))
        except Exception:
            pass   # snapshot optional — delta updates still work

        while True:
            await websocket.receive_text()   # keep alive / ping
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


def _is_cold_start() -> bool:
    try:
        from backend.scheduler import is_cold_start
        return is_cold_start()
    except Exception:
        return False






def _migrate_db_schema_region() -> None:
    """Add region_code and resolution columns to hexes table if not present."""
    import sqlite3
    db_path = Path(__file__).resolve().parents[1] / "data" / "hydrasense.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for col, typ in [("region_code", "TEXT DEFAULT ''"), ("resolution", "INTEGER DEFAULT 8")]:
        try:
            cur.execute(f"ALTER TABLE hexes ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


@app.get("/", tags=["health"])
def health():
    from backend.onboarding.geopackage import list_onboarded_regions
    from backend.scheduler import is_cold_start
    return {
        "status": "ok",
        "service": "HydraSense Backend API",
        "version": "2.0.0",
        "architecture": "region-agnostic (HydraSense_Final.md)",
        "cold_start_guard_active": is_cold_start(),
        "onboarded_regions": list_onboarded_regions(),
        "reference": "HydraSense_Final.md §15.5",
    }
