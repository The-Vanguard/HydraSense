"""
backend/alerts/dedup.py — Phase 11
Implements SRS.md Section 17.1 (deduplication) and 17.2 (downgrade/recovery) exactly.

Decision table:
┌──────────────────────────────────────────────────────────────────────┐
│ new_tier ≥ Orange                                                     │
│   → reset consecutive_below_orange_cycles = 0                         │
│   → if new_tier > last_alert_tier                                     │
│        OR now - last_alert_timestamp ≥ 30 min:   FIRE alert          │
│      else:                                        SKIP (cooldown)     │
│                                                                       │
│ new_tier < Orange (Green or Yellow)                                   │
│   → increment consecutive_below_orange_cycles                         │
│   → if cycles ≥ 2:  emit RESOLVED downgrade event, reset counter     │
│   → always return DOWNGRADE (no CAP generated)                        │
└──────────────────────────────────────────────────────────────────────┘

Return value from `evaluate()`:
  ("fire",      updated_state)   — caller must generate CAP + log
  ("skip",      updated_state)   — dedup cooldown, do nothing
  ("downgrade", updated_state)   — log downgrade event, check resolved
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Literal

from .models import AlertState, ALERT_TIERS, tier_rank

COOLDOWN_MINUTES = 30
RESOLVE_CYCLES   = 2  # consecutive below-Orange cycles required before "resolved"

Decision = Literal["fire", "skip", "downgrade"]


def evaluate(
    state: AlertState,
    new_tier: str,
    now: datetime | None = None,
) -> tuple[Decision, AlertState]:
    """
    Evaluate dedup/downgrade logic against the current alert_state.

    Returns (decision, updated_state).
    The caller is responsible for persisting updated_state to the store.
    `now` is injectable for deterministic testing.

    Decision rules (SRS §17.1 and §17.2):
    ─────────────────────────────────────
    FIRE:      new_tier rank > last_alert_tier rank
               OR no alert yet sent for this hex
               OR cooldown elapsed (≥30 min since last alert)
               — requires new_tier to be in ALERT_TIERS only for the first-ever case
                 (§17.1 fires on escalation past any previously-sent tier level)

    SKIP:      new_tier in ALERT_TIERS, same or lower tier, within cooldown

    DOWNGRADE: new_tier NOT in ALERT_TIERS AND hex was previously in an alert state
               (i.e., last_alert_tier is Orange or Red)
               — increments consecutive_below_orange_cycles per §17.2
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Work on a copy so the original is not mutated before the caller persists
    st = AlertState(
        hex_id=state.hex_id,
        last_alert_tier=state.last_alert_tier,
        last_alert_timestamp=state.last_alert_timestamp,
        consecutive_below_orange_cycles=state.consecutive_below_orange_cycles,
    )

    # ── No prior alert sent for this hex ─────────────────────────────────────
    if st.last_alert_tier is None:
        if new_tier in ALERT_TIERS:
            # First-ever alert for this hex — fire
            st.last_alert_tier      = new_tier
            st.last_alert_timestamp = now
            st.consecutive_below_orange_cycles = 0
            return "fire", st
        else:
            # Hex has never been alerted and is not in alert tier — nothing to do
            # No state change needed; return skip so caller doesn't log a spurious downgrade
            return "skip", st

    # ── Hex has a prior alert state ───────────────────────────────────────────
    if new_tier in ALERT_TIERS:
        # Orange or Red — reset downgrade counter
        st.consecutive_below_orange_cycles = 0
        if _should_fire(st, new_tier, now):
            st.last_alert_tier      = new_tier
            st.last_alert_timestamp = now
            return "fire", st
        else:
            return "skip", st

    else:
        # Below Orange (Green or Yellow)
        if st.last_alert_tier in ALERT_TIERS:
            # Was previously alerted at Orange/Red — this is a genuine tier drop
            st.consecutive_below_orange_cycles += 1
            return "downgrade", st
        else:
            # Was previously at a non-alert tier (Green/Yellow) and is still non-alert
            # §17.1: fire if new tier is strictly above previous
            if _should_fire(st, new_tier, now):
                st.last_alert_tier      = new_tier
                st.last_alert_timestamp = now
                st.consecutive_below_orange_cycles = 0
                return "fire", st
            else:
                return "skip", st



def _should_fire(state: AlertState, new_tier: str, now: datetime) -> bool:
    """
    §17.1: fire if:
      (a) new_tier rank > last_alert_tier rank   (tier escalation), OR
      (b) last_alert_timestamp is None (first ever alert for this hex), OR
      (c) time since last alert ≥ COOLDOWN_MINUTES
    """
    # No alert ever sent for this hex
    if state.last_alert_tier is None or state.last_alert_timestamp is None:
        return True

    # Tier increased past last alerted tier
    if tier_rank(new_tier) > tier_rank(state.last_alert_tier):
        return True

    # Cooldown elapsed
    elapsed = now - state.last_alert_timestamp
    if elapsed >= timedelta(minutes=COOLDOWN_MINUTES):
        return True

    return False


def is_resolved(state: AlertState) -> bool:
    """True when the hex has been below Orange for ≥ RESOLVE_CYCLES consecutive cycles."""
    return state.consecutive_below_orange_cycles >= RESOLVE_CYCLES
