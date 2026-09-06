"""
backend/alerts/models.py — Phase 11
Pure-Python dataclasses mirroring SRS.md Section 14 schema for:
  - alert_state  (per-hex dedup state)
  - AlertRecord  (row in alerts table)
  - DowngradeEvent (logged on tier drop, never a CAP)
  - FeedItem     (union type returned by GET /alert/feed)

No SQLAlchemy — storage is injected via store.py.
When Phase 8 (Guhan-10) DB backend lands, only store.py changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Tier ordering — used by dedup comparison (§17.1)
# ---------------------------------------------------------------------------
TIER_ORDER: dict[str, int] = {
    "Green":  0,
    "Yellow": 1,
    "Orange": 2,
    "Red":    3,
}

ALERT_TIERS = {"Orange", "Red"}


def tier_rank(tier: str) -> int:
    return TIER_ORDER.get(tier, -1)


# ---------------------------------------------------------------------------
# alert_state — SRS §14
# ---------------------------------------------------------------------------
@dataclass
class AlertState:
    hex_id: str
    last_alert_tier: Optional[str] = None          # None means no alert ever sent
    last_alert_timestamp: Optional[datetime] = None # UTC
    consecutive_below_orange_cycles: int = 0


# ---------------------------------------------------------------------------
# alerts — SRS §14
# ---------------------------------------------------------------------------
@dataclass
class AlertRecord:
    alert_id: str                   # HYDRASENSE-WYD-YYYY-NNNNNN
    hex_id: str
    timestamp: datetime             # UTC
    tier: str
    risk_score: float
    confidence_score: float
    lead_time_min: Optional[int]    # hour-granular per SRS §12, None if no forecast crossing
    lead_time_basis: str
    cap_xml: str                    # full CAP 1.2 XML string
    cap_payload: dict               # structured version for JSONB / JSON API
    delivered_channels: list[str] = field(default_factory=list)
    type: str = "cap"               # always "cap" — distinguishes from DowngradeEvent in feed


# ---------------------------------------------------------------------------
# Downgrade event — logged to feed but never a CAP (§17.2)
# ---------------------------------------------------------------------------
@dataclass
class DowngradeEvent:
    event_id: str                   # e.g. "DOWNGRADE-8860064e61fffff-1"
    hex_id: str
    timestamp: datetime             # UTC
    from_tier: str                  # tier that was last alerted
    to_tier: str                    # new (lower) tier
    resolved: bool = False          # True once consecutive_below_orange_cycles >= 2
    type: str = "downgrade"         # always "downgrade"
