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


class ExerciseRequest(BaseModel):
    region_code:   str
    scenario_tier: str = "Red"          # the DRILL tier; the real current score is reported alongside
    hazard:        str = "landslide"


_HAZARD_TRIGGER = {"landslide": "SATURATION_LANDSLIDE", "flood": "SATURATION_FLOOD"}
_TIER_RANK = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}


@router.get("/region-status")
def region_status():
    """Worst CURRENT tier per region for the console's region strip (real stored scores only)."""
    from backend import repository
    out = []
    for code in repository.REGION_BBOX:
        rows = repository.get_risk_map_data(code)
        counts = {t: 0 for t in _TIER_RANK}
        village_worst: dict[str, str] = {}          # village (or place) name -> worst tier among its scored cells
        for r in rows:
            t = r.get("tier")
            if t in counts:
                counts[t] += 1
                name = r.get("village") or r["hex_id"]
                if name not in village_worst or _TIER_RANK[t] > _TIER_RANK[village_worst[name]]:
                    village_worst[name] = t
        village_counts = {t: 0 for t in _TIER_RANK}
        for t in village_worst.values():
            village_counts[t] += 1
        worst = max((t for t, n in counts.items() if n), key=_TIER_RANK.get, default=None)
        peak, last = _peak_rain_and_last_update([r["hex_id"] for r in rows])
        s, n, w, e = repository.REGION_BBOX[code]
        out.append(dict(region_code=code, worst_tier=worst, scored_hexes=len(rows), tier_counts=counts,
                        village_tier_counts=village_counts, villages_with_scores=len(village_worst),
                        center=dict(lat=(s + n) / 2, lon=(w + e) / 2),
                        peak_rainfall_24h_mm=peak, last_updated=last,
                        region_label=(rows[0].get("region_label") if rows else None)))
    return {"regions": out, "basis": "latest stored score per hex (stale scores excluded), the same rows the map "
                                     "draws; a village takes the worst tier of its scored cells (cells outside every "
                                     "village footprint count toward the nearest village); peak rainfall is null "
                                     "where the 24 h rainfall was not stored"}


def _peak_rain_and_last_update(hex_ids: list[str]):
    """Max 24 h rainfall over the latest score of each hex (NULL-safe) and the newest score time."""
    from backend.database import get_db
    if not hex_ids:
        return None, None
    peak, last = None, None
    with get_db() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(risk_scores)").fetchall()]
        rain = "r.rainfall_24h" if "rainfall_24h" in cols else "NULL"
        for i in range(0, len(hex_ids), 500):
            chunk = hex_ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            p, l = conn.execute(
                f"SELECT MAX({rain}), MAX(r.timestamp) FROM risk_scores r JOIN (SELECT hex_id, MAX(id) mid "
                f"FROM risk_scores WHERE hex_id IN ({q}) GROUP BY hex_id) m ON r.id = m.mid", chunk).fetchone()
            if p is not None:
                peak = p if peak is None else max(peak, p)
            if l is not None:
                last = l if last is None else max(last, l)
    return (round(peak, 1) if peak is not None else None), last


@router.post("/exercise")
def start_exercise(req: ExerciseRequest):
    """
    v2 Sec. 16.3: raise a clearly labelled EXERCISE alert for a region so the two-person workflow can be
    demonstrated.  The alert is held at the gate like a real one; on authorisation a CAP with
    status=Exercise is built and NOTHING is fanned out.  The drill tier is the operator's scenario; the
    region's real current score is attached so the two are never confused.
    """
    from backend.alerts.gate import open_gate
    from backend.alerts.broadcast import TRIGGER_ACTIONS
    from backend import repository
    if req.scenario_tier not in ("Orange", "Red"):
        raise HTTPException(422, detail="scenario_tier must be Orange or Red")
    rows = repository.get_risk_map_data(req.region_code)
    if not rows:
        raise HTTPException(409, detail=f"region '{req.region_code}' has no current scores; "
                                        "run a scoring cycle for it first")
    top = max(rows, key=lambda r: r.get("risk_score") or 0.0)
    village = None
    try:                                              # the village containing the top hex, when onboarded
        from backend.routers import village as village_api
        from backend import village_rollup as vr
        layers = village_api.load_region_layers(req.region_code)
        for v in layers.villages:
            fp, _ = vr.footprint_hexes(v["geometry"])
            if top["hex_id"] in fp:
                village = v["name"]
                break
    except Exception:
        village = None
    trigger = _HAZARD_TRIGGER.get(req.hazard, "SATURATION_LANDSLIDE")
    context = dict(
        exercise=True, region_code=req.region_code, region_label=top.get("region_label"),
        village=village, hazard=req.hazard, trigger_type=trigger, scenario_tier=req.scenario_tier,
        real_hex_id=top["hex_id"], real_tier=top.get("tier"), real_risk_score=top.get("risk_score"),
        what_is_happening=(f"EXERCISE scenario: {req.scenario_tier} {req.hazard} alert. "
                           f"Real current score here is {round(top.get('risk_score') or 0)} ({top.get('tier')})."),
        what_to_do=TRIGGER_ACTIONS.get(trigger, "Take precautions now"),
    )
    gate_key = f"EX-{top['hex_id']}"
    g = open_gate(gate_key, risk_score=top.get("risk_score") or 0.0,
                  confidence=top.get("confidence_score") or 0.0, context=context)
    broadcast_sync({"type": "gate_pending", "hex_id": gate_key, "exercise": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "EXERCISE alert awaiting two-person authorisation"})
    return {**g.to_dict(), "banner": "Simulated feed. Exercise alert, nothing is being sent.",
            "reference": "HydraSense_v2 Sec. 16.3"}


@router.get("/{hex_id}")
def gate_state(hex_id: str):
    """Current two-person gate state for a hex."""
    return get_gate_state(hex_id)
