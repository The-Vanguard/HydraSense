"""
backend/alerts/gate.py
Two-Person Authorization Gate — Stage 5 (Final.md §17.4)

Red-tier CAP alerts require authorization from a SECOND human operator before
the alert is fanned out. The first operator's risk_engine cycle sets the
gate to PENDING. The second operator approves via POST /alert/gate/approve.

If no approval is received within GATE_TIMEOUT_MINUTES, the gate expires and
the alert is NOT sent (fail-safe: better to miss one cycle than to send a false
Red alert without human oversight).

Final.md §17.4 rules (frozen):
  - Only Red tier triggers the gate. Orange fires immediately (dedup permitting).
  - Gate state: PENDING | APPROVED | EXPIRED | BYPASSED
  - BYPASSED is only allowed when explicitly flagged (e.g. during drills).
  - Gate approval requires operator_id (any non-empty string — no auth in v1).
  - Timeout: GATE_TIMEOUT_MINUTES = 10 (one ingestion cycle window).
  - After approval: normal dedup/fanout runs with gate_approved=True.
  - Expired gate: log to audit trail, do NOT fire alert.

API surface (registered in main.py as /alert/gate/...):
  POST /alert/gate/approve   {hex_id, operator_id}
  GET  /alert/gate/pending   list all pending gate requests
  GET  /alert/gate/{hex_id}  current gate state for a hex
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]

GATE_TIMEOUT_MINUTES = 10
GateStatus = Literal["PENDING", "APPROVED", "EXPIRED", "BYPASSED", "NONE"]

_GATE_STATE_PATH = ROOT / "data" / "validation" / "gate_state.json"


class GateRequest:
    def __init__(
        self,
        hex_id:       str,
        risk_score:   float,
        confidence:   float,
        created_at:   str,
        status:       GateStatus = "PENDING",
        operator_id:  str = "",
        approved_at:  str = "",
        lead_time_min: int | None = None,
    ):
        self.hex_id        = hex_id
        self.risk_score    = risk_score
        self.confidence    = confidence
        self.created_at    = created_at
        self.status        = status
        self.operator_id   = operator_id
        self.approved_at   = approved_at
        self.lead_time_min = lead_time_min

    def to_dict(self) -> dict:
        return {
            "hex_id":        self.hex_id,
            "risk_score":    self.risk_score,
            "confidence":    self.confidence,
            "created_at":    self.created_at,
            "status":        self.status,
            "operator_id":   self.operator_id,
            "approved_at":   self.approved_at,
            "lead_time_min": self.lead_time_min,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GateRequest":
        return cls(
            hex_id        = d.get("hex_id", ""),
            risk_score    = float(d.get("risk_score", 0.0)),
            confidence    = float(d.get("confidence", 0.0)),
            created_at    = d.get("created_at", ""),
            status        = d.get("status", "NONE"),
            operator_id   = d.get("operator_id", ""),
            approved_at   = d.get("approved_at", ""),
            lead_time_min = d.get("lead_time_min"),
        )

    def is_expired(self) -> bool:
        if self.status != "PENDING":
            return False
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) - created >= timedelta(minutes=GATE_TIMEOUT_MINUTES)
        except Exception:
            return True


# ---------------------------------------------------------------------------
# File-backed gate store
# ---------------------------------------------------------------------------

def _load_all() -> dict[str, dict]:
    if not _GATE_STATE_PATH.exists():
        return {}
    try:
        return json.loads(_GATE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_all(data: dict) -> None:
    _GATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GATE_STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _get(hex_id: str) -> GateRequest | None:
    raw = _load_all().get(hex_id)
    if raw:
        return GateRequest.from_dict(raw)
    return None


def _save(req: GateRequest) -> None:
    all_gates = _load_all()
    all_gates[req.hex_id] = req.to_dict()
    _save_all(all_gates)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def open_gate(
    hex_id: str,
    risk_score: float,
    confidence: float,
    lead_time_min: int | None = None,
) -> GateRequest:
    """
    Create or reset a PENDING gate for a Red-tier hex.
    Called by risk_engine when tier=Red + is_persistent_threat=True.
    """
    req = GateRequest(
        hex_id        = hex_id,
        risk_score    = risk_score,
        confidence    = confidence,
        created_at    = datetime.now(timezone.utc).isoformat(),
        status        = "PENDING",
        lead_time_min = lead_time_min,
    )
    _save(req)
    print("[gate] PENDING gate opened for hex=%s risk=%.1f" % (hex_id, risk_score))
    return req


def approve_gate(hex_id: str, operator_id: str) -> dict[str, Any]:
    """
    Approve a PENDING gate. Returns result dict.
    operator_id must be non-empty (any string accepted in v1).
    """
    if not operator_id or not operator_id.strip():
        return {"success": False, "error": "operator_id must not be empty"}

    req = _get(hex_id)
    if req is None:
        return {"success": False, "error": "No gate found for hex_id=%s" % hex_id}

    if req.is_expired():
        req.status = "EXPIRED"
        _save(req)
        return {"success": False, "error": "Gate expired (>%d min). Re-trigger required." % GATE_TIMEOUT_MINUTES}

    if req.status != "PENDING":
        return {"success": False, "error": "Gate status is %s, not PENDING" % req.status}

    req.status      = "APPROVED"
    req.operator_id = operator_id.strip()
    req.approved_at = datetime.now(timezone.utc).isoformat()
    _save(req)
    print("[gate] APPROVED by operator=%s for hex=%s" % (operator_id, hex_id))
    return {
        "success":     True,
        "hex_id":      hex_id,
        "approved_at": req.approved_at,
        "operator_id": req.operator_id,
        "status":      "APPROVED",
    }


def check_gate(hex_id: str) -> GateStatus:
    """
    Return current gate status for a hex. Advances PENDING -> EXPIRED if timed out.
    NONE if no gate has ever been opened for this hex.
    """
    req = _get(hex_id)
    if req is None:
        return "NONE"
    if req.is_expired() and req.status == "PENDING":
        req.status = "EXPIRED"
        _save(req)
    return req.status


def get_gate_state(hex_id: str) -> dict[str, Any]:
    """Return full gate dict for API response."""
    req = _get(hex_id)
    if req is None:
        return {"hex_id": hex_id, "status": "NONE"}
    if req.is_expired() and req.status == "PENDING":
        req.status = "EXPIRED"
        _save(req)
    return req.to_dict()


def list_pending_gates() -> list[dict[str, Any]]:
    """Return all currently PENDING (non-expired) gate requests."""
    all_gates = _load_all()
    pending = []
    for hex_id, raw in all_gates.items():
        req = GateRequest.from_dict(raw)
        if req.status == "PENDING":
            if req.is_expired():
                req.status = "EXPIRED"
                _save(req)
            else:
                pending.append(req.to_dict())
    return pending
