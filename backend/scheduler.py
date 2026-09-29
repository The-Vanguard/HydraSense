"""
backend/scheduler.py — Two-loop scheduling (Final.md §14.6 / §15.7)

Implements the two independent loops Final.md §14.6 requires:

  Slow loop  — APScheduler AsyncIOScheduler, max_instances=1
               Runs every SLOW_INTERVAL_SECONDS (default 900 = 15 min).
               Recomputes dynamic features, FS, and risk per hex for all
               onboarded regions. Must not overlap; max_instances=1 is the
               literal mechanism behind §14.8 checklist item 1.

  Fast loop  — persistent asyncio.Task
               Simulates IoT sensor tick every FAST_INTERVAL_SECONDS (default 10s).
               Updates iot_anomaly_flag per hex independently of the slow loop.
               The two loops write different fields so they never overwrite each other.

Cold-start guard (Final.md §14.6):
  The very first slow-loop cycle after startup is flagged as cold-start.
  During cold-start, risk_engine.run_cycle() sets a flag that prevents any
  Orange/Red alert from firing — the pipeline must complete at least one full
  cycle before alerts are allowed, so onboarding a new region live on stage
  does not fire a spurious alert.

Usage (wired into FastAPI lifespan in main.py):
    from backend.scheduler import lifespan
    app = FastAPI(lifespan=lifespan, ...)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

log = logging.getLogger("hydrasense.scheduler")

SLOW_INTERVAL_SECONDS = 900   # 15 min — matched to Open-Meteo's own update cadence
FAST_INTERVAL_SECONDS = 10    # IoT simulation tick

_cold_start: bool = True      # cleared after first successful slow cycle


def is_cold_start() -> bool:
    """True during the very first cycle after startup — gate checked by risk_engine."""
    return _cold_start


def _village_cycles() -> None:
    """Village persistence for opted-in regions that have been onboarded (see village_cycle.py)."""
    from backend.risk_engine import scoring_regions
    from backend.village_cycle import run_village_cycle
    for code in scoring_regions():
        try:
            run_village_cycle(code, cold_start=_cold_start)
        except Exception as exc:                       # a missing GeoPackage must not stop the loop
            log.warning("[village_cycle] %s skipped: %s", code, exc)


async def _slow_loop() -> None:
    """
    Slow refresh loop — recompute dynamic features, FS, risk per hex for all regions.
    max_instances=1 semantics enforced via asyncio.Lock so overlapping cycles are
    skipped rather than queued (the same guarantee APScheduler max_instances=1 gives).
    """
    global _cold_start
    lock = asyncio.Lock()
    await asyncio.sleep(2)  # initial brief warm-up delay

    while True:
        if not lock.locked():
            async with lock:
                try:
                    from backend.risk_engine import run_cycle_all_regions
                    await asyncio.to_thread(run_cycle_all_regions)
                    await asyncio.to_thread(_village_cycles)
                    if _cold_start:
                        _cold_start = False
                        log.info("[slow_loop] cold-start cleared — alerts now enabled")
                except Exception as exc:
                    log.error("[slow_loop] cycle error: %s", exc, exc_info=True)
        await asyncio.sleep(SLOW_INTERVAL_SECONDS)


async def _fast_loop() -> None:
    """
    Fast IoT simulation loop — updates iot_anomaly_flag per hex every FAST_INTERVAL_SECONDS.
    Runs independently so sensor readings don't have to wait for the slow 15-min cycle.
    """
    while True:
        await asyncio.sleep(FAST_INTERVAL_SECONDS)
        try:
            from backend.ingest.iot_sim import tick_iot_simulation
            await asyncio.to_thread(tick_iot_simulation)
        except Exception as exc:
            log.debug("[fast_loop] iot sim tick error: %s", exc)


@asynccontextmanager
async def lifespan(app):
    """
    FastAPI lifespan context — starts both loops on startup, cancels on shutdown.
    Replace @app.on_event('startup') in main.py with:
        app = FastAPI(lifespan=scheduler.lifespan, ...)
    """
    slow_task = asyncio.create_task(_slow_loop(), name="hydrasense-slow-loop")
    fast_task = asyncio.create_task(_fast_loop(), name="hydrasense-fast-loop")
    log.info("[scheduler] slow loop started (interval=%ds, cold-start guard active)",
             SLOW_INTERVAL_SECONDS)
    log.info("[scheduler] fast IoT loop started (interval=%ds)", FAST_INTERVAL_SECONDS)

    yield   # app runs here

    slow_task.cancel()
    fast_task.cancel()
    try:
        await asyncio.gather(slow_task, fast_task, return_exceptions=True)
    except Exception:
        pass
    log.info("[scheduler] loops stopped on shutdown")
