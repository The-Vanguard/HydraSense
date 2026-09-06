"""
backend/alerts/store.py — Phase 11
Thread-safe in-memory store for alert_state and alerts tables.

Interface is identical to what a SQLAlchemy/PostGIS implementation would expose,
so swapping to Phase 8's DB layer requires changing only this file.

SRS.md Section 14 schema:
  alert_state(hex_id PK, last_alert_tier, last_alert_timestamp, consecutive_below_orange_cycles)
  alerts(alert_id, hex_id, timestamp, tier, cap_payload JSONB, delivered_channels TEXT[])
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from .models import AlertRecord, AlertState, DowngradeEvent


class AlertStore:
    """
    Single shared instance — import `store` from this module.
    All public methods are thread-safe via a reentrant lock.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # hex_id -> AlertState
        self._states: dict[str, AlertState] = {}
        # ordered list of AlertRecord (newest appended last)
        self._alerts: list[AlertRecord] = []
        # ordered list of DowngradeEvent (newest appended last)
        self._downgrades: list[DowngradeEvent] = []
        # monotonic counter for alert_id generation
        self._counter: int = 0
        self._downgrade_counter: int = 0

    # ------------------------------------------------------------------
    # alert_state operations
    # ------------------------------------------------------------------

    def get_state(self, hex_id: str) -> AlertState:
        with self._lock:
            return self._states.get(hex_id, AlertState(hex_id=hex_id))

    def upsert_state(self, state: AlertState) -> None:
        with self._lock:
            self._states[state.hex_id] = state

    # ------------------------------------------------------------------
    # alerts table operations
    # ------------------------------------------------------------------

    def next_alert_id(self) -> str:
        with self._lock:
            self._counter += 1
            year = datetime.now(timezone.utc).year
            return f"HYDRASENSE-WYD-{year}-{self._counter:06d}"

    def append_alert(self, record: AlertRecord) -> None:
        with self._lock:
            self._alerts.append(record)

    def get_alerts(self) -> list[AlertRecord]:
        with self._lock:
            return list(self._alerts)

    # ------------------------------------------------------------------
    # downgrade events
    # ------------------------------------------------------------------

    def next_downgrade_id(self, hex_id: str) -> str:
        with self._lock:
            self._downgrade_counter += 1
            return f"DOWNGRADE-{hex_id}-{self._downgrade_counter}"

    def append_downgrade(self, event: DowngradeEvent) -> None:
        with self._lock:
            self._downgrades.append(event)

    def get_downgrades(self) -> list[DowngradeEvent]:
        with self._lock:
            return list(self._downgrades)

    def mark_resolved(self, hex_id: str) -> None:
        """Mark the most recent downgrade event for this hex as resolved."""
        with self._lock:
            for ev in reversed(self._downgrades):
                if ev.hex_id == hex_id and not ev.resolved:
                    ev.resolved = True
                    break

    # ------------------------------------------------------------------
    # feed: combined alerts + downgrades, newest first (§15 GET /alert/feed)
    # ------------------------------------------------------------------

    def get_feed(self) -> list[dict]:
        with self._lock:
            items: list[dict] = []

            for a in self._alerts:
                items.append({
                    "type":             a.type,
                    "alert_id":         a.alert_id,
                    "hex_id":           a.hex_id,
                    "timestamp":        a.timestamp.isoformat(),
                    "tier":             a.tier,
                    "risk_score":       a.risk_score,
                    "confidence_score": a.confidence_score,
                    "lead_time_min":    a.lead_time_min,
                    "lead_time_basis":  a.lead_time_basis,
                    "delivered_channels": a.delivered_channels,
                    "cap_payload":      a.cap_payload,
                })

            for d in self._downgrades:
                items.append({
                    "type":       d.type,
                    "event_id":   d.event_id,
                    "hex_id":     d.hex_id,
                    "timestamp":  d.timestamp.isoformat(),
                    "from_tier":  d.from_tier,
                    "to_tier":    d.to_tier,
                    "resolved":   d.resolved,
                })

            # newest first — sort by timestamp string (ISO 8601 sorts lexicographically)
            items.sort(key=lambda x: x["timestamp"], reverse=True)
            return items


# Module-level singleton — import this in router.py and tests
store = AlertStore()
