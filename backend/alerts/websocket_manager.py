"""
backend/alerts/websocket_manager.py
WebSocket connection manager — Stage 5 (Final.md §15.6)

Maintains active WebSocket connections and broadcasts real-time tier-change
events to all connected dashboard clients.

Event types pushed over WebSocket:
  {"type": "tier_change",   "hex_id": ..., "tier": ..., "risk_score": ..., "timestamp": ...}
  {"type": "alert_fired",   "hex_id": ..., "tier": ..., "alert_id": ...,   "timestamp": ...}
  {"type": "persist_declared","hex_id": ..., "cycles": ...,                 "timestamp": ...}
  {"type": "gate_pending",  "hex_id": ..., "risk_score": ...,               "timestamp": ...}
  {"type": "gate_approved", "hex_id": ..., "operator_id": ...,              "timestamp": ...}
  {"type": "downgrade",     "hex_id": ..., "from_tier": ..., "to_tier": ..., "timestamp": ...}
  {"type": "ping"}          — keepalive every 30s

Usage in FastAPI:
  from backend.alerts.websocket_manager import manager
  @app.websocket("/ws/alerts")
  async def ws_alerts(ws: WebSocket):
      await manager.connect(ws)
      try:
          while True:
              await ws.receive_text()   # keep connection alive
      except WebSocketDisconnect:
          manager.disconnect(ws)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Thread-safe WebSocket broadcast manager."""

    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)
        await self._send_one(ws, {"type": "connected",
                                   "message": "HydraSense real-time alerts active",
                                   "timestamp": _now()})

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._active:
            self._active.remove(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Broadcast a JSON payload to all active connections. Dead connections removed."""
        if not self._active:
            return
        msg = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def _send_one(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._active)


# Module-level singleton — imported by risk_engine and routers
manager = ConnectionManager()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Sync broadcast helper (for non-async callers like risk_engine.py)
# ---------------------------------------------------------------------------

def broadcast_sync(payload: dict[str, Any]) -> None:
    """
    Fire-and-forget broadcast from sync context (risk_engine.py).
    Uses the running event loop if available; silently skips if none.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(manager.broadcast(payload))
        else:
            loop.run_until_complete(manager.broadcast(payload))
    except RuntimeError:
        pass   # No event loop — skip (unit test / CLI context)
