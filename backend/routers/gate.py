"""
backend/routers/gate.py
Two-Person Gate API — Stage 5 (Final.md §17.4)

POST /alert/gate/reject     — either role rejects a pending alert
GET  /alert/gate/pending    — list all pending (unresolved) gate requests
GET  /alert/gate/{hex_id}  — gate state for a specific hex
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.alerts.gate import (
    reject_gate, list_pending_gates, get_gate_state,
    GATE_TIMEOUT_MINUTES,
)
from backend.alerts.websocket_manager import broadcast_sync
from datetime import datetime, timezone

router = APIRouter(prefix="/alert/gate", tags=["gate"])


class RejectRequest(BaseModel):
    hex_id:      str
    operator_id: str
    role:        str = "duty_officer"
    reason:      str = ""


# NOTE: POST /alert/gate/approve lives in backend/alerts/router.py (it also fans the alert out once the
# second approval lands).  Reject is here.
@router.post("/reject")
def reject(req: RejectRequest):
    """Either required role rejects a pending alert; nothing is sent."""
    result = reject_gate(req.hex_id, req.operator_id, req.role, req.reason)
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["error"])
    broadcast_sync({"type": "gate_rejected", "hex_id": req.hex_id, "operator_id": req.operator_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "Alert rejected at the authorization gate; nothing was sent"})
    return {**result, "reference": "HydraSense_v2 Sec. 10.3"}


@router.get("/pending")
def pending_gates():
    """
    List all pending two-person gate requests (Red-tier alerts awaiting approval).
    Dashboard polls this to show the operator the pending alert queue.
    """
    return {
        "pending_gates":    list_pending_gates(),
        "timeout_min":      GATE_TIMEOUT_MINUTES,
        "note": "Each gate expires after %d minutes if not approved." % GATE_TIMEOUT_MINUTES,
    }


@router.get("/{hex_id}")
def gate_state(hex_id: str):
    """Current two-person gate state for a hex."""
    return get_gate_state(hex_id)
