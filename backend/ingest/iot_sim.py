"""
backend/ingest/iot_sim.py — Fast IoT simulation tick (Final.md §14.6)

Called by the fast loop in scheduler.py every FAST_INTERVAL_SECONDS (10s).
Simulates an MQTT sensor telemetry tick and broadcasts via WebSocket.
Independent of the slow 15-min refresh cycle.
"""
from __future__ import annotations
import random
import logging
from datetime import datetime, timezone

log = logging.getLogger("hydrasense.iot_sim")

_sensor_offline: bool = False

def set_sensor_offline(offline: bool) -> bool:
    global _sensor_offline
    _sensor_offline = offline
    return _sensor_offline

def is_sensor_offline() -> bool:
    return _sensor_offline


def tick_iot_simulation() -> None:
    """
    Simulate one IoT sensor tick.
    Broadcasts live sensor observations across WebSocket to keep the
    command console active and dynamic in real time.
    """
    try:
        from backend.database import get_db
        from backend.alerts.websocket_manager import broadcast_sync

        with get_db() as conn:
            rows = conn.execute("SELECT hex_id FROM hexes LIMIT 20").fetchall()
        if not rows:
            return

        target = random.choice(rows)["hex_id"]
        now_ts = datetime.now(timezone.utc).isoformat()

        if _sensor_offline:
            # Final.md §14.5 deliberate sensor failure demo
            broadcast_sync({
                "type": "sensor_offline",
                "hex_id": target,
                "sensor_id": f"MQTT-TILT-{target[:6].upper()}",
                "status": "OFFLINE",
                "fallback": "Satellite / ERA5 forecast active",
                "timestamp": now_ts,
            })
            return

        # Normal telemetry tick
        is_elevated = random.random() < 0.25
        val = round(random.uniform(35.0, 95.0), 1) if is_elevated else round(random.uniform(2.0, 18.0), 1)
        sensor_type = random.choice(["rainfall", "soil_moisture", "tilt"])

        broadcast_sync({
            "type": "telemetry_tick",
            "hex_id": target,
            "sensor_type": sensor_type,
            "value": val,
            "elevated": is_elevated,
            "sensor_id": f"MQTT-{sensor_type[:4].upper()}-{target[:6].upper()}",
            "timestamp": now_ts,
        })
    except Exception as exc:
        log.debug("[iot_sim] tick error: %s", exc)
