"""
backend/routers/gate.py
Two-Person Gate API — Stage 5 (Final.md §17.4)

POST /alert/gate/approve    — second operator approves a pending Red alert
GET  /alert/gate/pending    — list all pending (unresolved) gate requests
GET  /alert/gate/{hex_id}  — gate state for a specific hex
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.alerts.gate import (
    approve_gate, list_pending_gates, get_gate_state,
    GATE_TIMEOUT_MINUTES,
)
from backend.alerts.websocket_manager import broadcast_sync
from datetime import datetime, timezone

router = APIRouter(prefix="/alert/gate", tags=["gate"])


class ApproveRequest(BaseModel):
    hex_id:      str
    operator_id: str


@router.post("/approve")
def approve(req: ApproveRequest):
    """
    Second-operator approval for a pending Red-tier alert (Final.md §17.4).
    After approval, the next ingestion cycle will see gate=APPROVED and fire the CAP.
    """
    if not req.operator_id.strip():
        raise HTTPException(status_code=422, detail="operator_id must not be empty")

    result = approve_gate(req.hex_id, req.operator_id)
    if not result["success"]:
        raise HTTPException(status_code=409, detail=result["error"])

    # Broadcast gate approval to dashboard
    broadcast_sync({
        "type":        "gate_approved",
        "hex_id":      req.hex_id,
        "operator_id": req.operator_id,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "message":     "Red alert gate approved — CAP will fire on next cycle",
    })

    return {
        **result,
        "next_step": "Red CAP alert will fire on the next risk_engine ingestion cycle.",
        "timeout_min": GATE_TIMEOUT_MINUTES,
        "reference": "Final.md §17.4",
    }


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
