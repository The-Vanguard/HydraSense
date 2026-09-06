"""
backend/alerts/router.py — Phase 11
FastAPI router exposing:

  POST /alert/trigger   internal endpoint — auto-called on Orange/Red risk_scores write
  GET  /alert/feed      dashboard feed of CAP alerts + downgrade events (§15)

SRS.md Section 15, 17.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .cap_generator import generate_cap_xml
from .dedup import evaluate, is_resolved
from .fanout import fanout
from .models import AlertRecord, DowngradeEvent
from .store import store

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TriggerRequest(BaseModel):
    hex_id:           str
    tier:             str
    risk_score:       float = Field(..., ge=0, le=100)
    confidence_score: float = Field(..., ge=0, le=100)
    lead_time_min:    Optional[int]  = None   # hour-granular per SRS §12, or None
    lead_time_basis:  str            = "no_red_crossing_in_forecast_window"
    nearest_shelter:  Optional[dict] = None   # forwarded from GET /shelters/nearest/{hex_id}


class TriggerResponse(BaseModel):
    action:    str          # "fired" | "skipped" | "downgrade"
    alert_id:  Optional[str] = None
    event_id:  Optional[str] = None
    reason:    Optional[str] = None
    resolved:  Optional[bool] = None  # only set on downgrade action


# ---------------------------------------------------------------------------
# POST /alert/trigger
# ---------------------------------------------------------------------------

@router.post("/alert/trigger", response_model=TriggerResponse, status_code=200)
def trigger_alert(req: TriggerRequest) -> TriggerResponse:
    """
    Internal endpoint — auto-called whenever a risk_scores write results in
    tier = Orange or Red (or when tier drops, to track downgrade state).

    §17.1 Dedup: only fires if tier increased OR 30-min cooldown elapsed.
    §17.2 Downgrade: tier drop increments counter; ≥2 cycles → resolved event.
    """
    # Validate tier value
    valid_tiers = {"Green", "Yellow", "Orange", "Red"}
    if req.tier not in valid_tiers:
        raise HTTPException(status_code=422, detail=f"tier must be one of {valid_tiers}")

    # Validate lead_time_min is hour-granular (SRS §12)
    if req.lead_time_min is not None and req.lead_time_min % 60 != 0:
        raise HTTPException(
            status_code=422,
            detail=f"lead_time_min must be a multiple of 60 (hour-granular per SRS §12). "
                   f"Got {req.lead_time_min}."
        )

    now   = datetime.now(timezone.utc)
    state = store.get_state(req.hex_id)
    decision, updated_state = evaluate(state, req.tier, now=now)

    # ── FIRE ────────────────────────────────────────────────────────────────
    if decision == "fire":
        alert_id          = store.next_alert_id()
        cap_xml, cap_dict = generate_cap_xml(
            alert_id       = alert_id,
            hex_id         = req.hex_id,
            tier           = req.tier,
            risk_score     = req.risk_score,
            confidence_score = req.confidence_score,
            lead_time_min  = req.lead_time_min,
            lead_time_basis = req.lead_time_basis,
            nearest_shelter = req.nearest_shelter,
        )

        record = AlertRecord(
            alert_id         = alert_id,
            hex_id           = req.hex_id,
            timestamp        = now,
            tier             = req.tier,
            risk_score       = req.risk_score,
            confidence_score = req.confidence_score,
            lead_time_min    = req.lead_time_min,
            lead_time_basis  = req.lead_time_basis,
            cap_xml          = cap_xml,
            cap_payload      = cap_dict,
        )

        # Persist alert first, then fan out
        store.append_alert(record)
        delivered = fanout(record)
        record.delivered_channels = delivered

        # Persist updated alert_state (last_alert_tier + timestamp already set by evaluate)
        store.upsert_state(updated_state)

        logger.info("Alert FIRED: %s hex=%s tier=%s channels=%s",
                    alert_id, req.hex_id, req.tier, delivered)

        return TriggerResponse(action="fired", alert_id=alert_id)

    # ── SKIP (cooldown / same tier within window) ────────────────────────────
    elif decision == "skip":
        store.upsert_state(updated_state)
        logger.info("Alert SKIPPED (dedup): hex=%s tier=%s", req.hex_id, req.tier)
        return TriggerResponse(
            action="skipped",
            reason=f"Tier '{req.tier}' already alerted within 30-min cooldown window."
        )

    # ── DOWNGRADE ────────────────────────────────────────────────────────────
    else:  # decision == "downgrade"
        store.upsert_state(updated_state)
        resolved = is_resolved(updated_state)

        event_id = store.next_downgrade_id(req.hex_id)
        last_tier = state.last_alert_tier or "unknown"
        ev = DowngradeEvent(
            event_id   = event_id,
            hex_id     = req.hex_id,
            timestamp  = now,
            from_tier  = last_tier,
            to_tier    = req.tier,
            resolved   = resolved,
        )
        store.append_downgrade(ev)

        if resolved:
            store.mark_resolved(req.hex_id)
            logger.info("Downgrade RESOLVED: hex=%s cycles=%d",
                        req.hex_id, updated_state.consecutive_below_orange_cycles)
        else:
            logger.info("Downgrade logged (not resolved): hex=%s cycles=%d",
                        req.hex_id, updated_state.consecutive_below_orange_cycles)

        return TriggerResponse(
            action   = "downgrade",
            event_id = event_id,
            reason   = (
                "Tier dropped below Orange. "
                f"Consecutive below-Orange cycles: "
                f"{updated_state.consecutive_below_orange_cycles}/"
                f"2 required for resolved."
            ),
            resolved = resolved,
        )


# ---------------------------------------------------------------------------
# GET /alert/feed
# ---------------------------------------------------------------------------

@router.get("/alert/feed")
def alert_feed() -> list[dict]:
    """
    Returns combined list of CAP alerts + downgrade events, newest first.
    Each item has `type: "cap"` or `type: "downgrade"` — frontend renders them
    as visually distinct items per SRS §17.
    """
    return store.get_feed()
