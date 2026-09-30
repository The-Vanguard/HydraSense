"""
backend/alerts/persistent_threat.py
Persistent Threat Detector — Stage 5 (Final.md §17.3)

A "Persistent Threat" is declared when a hex sustains Orange or Red tier for
PERSIST_CYCLES_REQUIRED consecutive ingestion cycles without interruption.

Purpose: filter single-cycle spike alerts (sensor noise, data gap artefacts)
from genuine multi-cycle escalations. The two-person gate (Red tier) is only
triggered on a Persistent Threat declaration, not on first-cycle Red.

State is stored per-hex in the AlertState via persistent_orange_red_cycles
(new field, back-compat with existing store — zero if key absent).

Final.md §17.3 rules (frozen):
  - Orange threshold: PERSIST_CYCLES_REQUIRED = 2 consecutive cycles
  - Red threshold:    PERSIST_CYCLES_REQUIRED = 2 consecutive cycles
    (Red additionally requires two-person gate — see gate.py)
  - A single below-Orange cycle RESETS the counter (strict persistence)
  - Persistent Threat record written to data/validation/ for audit

API surface:
  is_persistent_threat(hex_id, new_tier) -> bool
  record_cycle(hex_id, new_tier)         -> PersistentThreatState
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Consecutive Orange/Red cycles required to declare a Persistent Threat
PERSIST_CYCLES_REQUIRED = 2

# File-backed state (same pattern as alerts/store.py — no new DB dependency)
_PERSIST_STATE_PATH = ROOT / "data" / "validation" / "persistent_threat_state.json"


class PersistentThreatState:
    def __init__(self, hex_id: str, cycles: int = 0, last_tier: str = "",
                 declared: bool = False, declared_at: str = ""):
        self.hex_id      = hex_id
        self.cycles      = cycles          # consecutive Orange/Red cycles
        self.last_tier   = last_tier       # last recorded tier
        self.declared    = declared        # True once threshold crossed
        self.declared_at = declared_at     # ISO timestamp of declaration

    def to_dict(self) -> dict:
        return {
            "hex_id":      self.hex_id,
            "cycles":      self.cycles,
            "last_tier":   self.last_tier,
            "declared":    self.declared,
            "declared_at": self.declared_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PersistentThreatState":
        return cls(
            hex_id      = d.get("hex_id", ""),
            cycles      = int(d.get("cycles", 0)),
            last_tier   = d.get("last_tier", ""),
            declared    = bool(d.get("declared", False)),
            declared_at = d.get("declared_at", ""),
        )


# ---------------------------------------------------------------------------
# File-backed state store (thread-safe enough for single-process FastAPI)
# ---------------------------------------------------------------------------

def _load_all() -> dict[str, dict]:
    if not _PERSIST_STATE_PATH.exists():
        return {}
    try:
        return json.loads(_PERSIST_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_all(data: dict) -> None:
    _PERSIST_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PERSIST_STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _get_state(hex_id: str) -> PersistentThreatState:
    all_states = _load_all()
    raw = all_states.get(hex_id)
    if raw:
        return PersistentThreatState.from_dict(raw)
    return PersistentThreatState(hex_id=hex_id)


_STATE_LOCK = threading.RLock()     # the slow cycle scores hexes in parallel threads


def _save_state(state: PersistentThreatState) -> None:
    with _STATE_LOCK:
        all_states = _load_all()
        all_states[state.hex_id] = state.to_dict()
        _save_all(all_states)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

ALARM_TIERS = {"Orange", "Red"}


def record_cycle(hex_id: str, new_tier: str) -> PersistentThreatState:
    """
    Record one ingestion cycle result for a hex.
    Updates consecutive cycle counter and returns updated state.
    Call this on EVERY cycle (not just Orange/Red).
    """
    state = _get_state(hex_id)
    now   = datetime.now(timezone.utc).isoformat()

    if new_tier in ALARM_TIERS:
        state.cycles    += 1
        state.last_tier  = new_tier
        if not state.declared and state.cycles >= PERSIST_CYCLES_REQUIRED:
            state.declared    = True
            state.declared_at = now
    else:
        # Below Orange — reset counter (strict persistence rule)
        state.cycles    = 0
        state.last_tier = new_tier
        state.declared  = False
        state.declared_at = ""

    _save_state(state)
    return state


def is_persistent_threat(hex_id: str) -> bool:
    """
    Return True if this hex is currently in a declared Persistent Threat state.
    Does NOT advance the counter — call record_cycle() first.
    """
    return _get_state(hex_id).declared


def get_threat_state(hex_id: str) -> dict[str, Any]:
    """Return current persistent threat state dict for API / tooltip."""
    return _get_state(hex_id).to_dict()


def reset_threat(hex_id: str) -> None:
    """Explicitly reset persistent threat state (e.g. after two-person gate approval)."""
    state = _get_state(hex_id)
    state.cycles      = 0
    state.declared    = False
    state.declared_at = ""
    _save_state(state)
