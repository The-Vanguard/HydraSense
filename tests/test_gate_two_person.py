"""tests/test_gate_two_person.py -- v2 Sec. 10.3: an alert needs two different people in two different roles."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.alerts import gate  # noqa: E402

HEX = "8860064e61fffff"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "_GATE_STATE_PATH", tmp_path / "gate_state.json")


def test_zero_one_two_progression():
    gate.open_gate(HEX, 90.0, 60.0)
    assert gate.get_gate_state(HEX)["approvals_count"] == 0
    r1 = gate.approve_gate(HEX, "asha", "duty_officer")
    assert r1["success"] and r1["status"] == "PENDING" and r1["approvals_count"] == 1
    assert r1["roles_needed"] == ["district_authority"]
    assert gate.check_gate(HEX) == "PENDING"
    r2 = gate.approve_gate(HEX, "ravi", "district_authority")
    assert r2["status"] == "APPROVED" and r2["approvals_count"] == 2
    assert gate.check_gate(HEX) == "APPROVED"


def test_same_person_cannot_approve_twice_even_with_the_other_role():
    gate.open_gate(HEX, 90.0, 60.0)
    gate.approve_gate(HEX, "Asha", "duty_officer")
    r = gate.approve_gate(HEX, "asha", "district_authority")          # case-insensitive
    assert not r["success"] and "already approved" in r["error"]
    assert gate.check_gate(HEX) == "PENDING"


def test_same_role_cannot_give_both_approvals():
    gate.open_gate(HEX, 90.0, 60.0)
    gate.approve_gate(HEX, "asha", "duty_officer")
    r = gate.approve_gate(HEX, "meera", "duty_officer")
    assert not r["success"] and "role" in r["error"]
    assert gate.check_gate(HEX) == "PENDING"


def test_unknown_role_and_empty_operator_rejected():
    gate.open_gate(HEX, 90.0, 60.0)
    assert not gate.approve_gate(HEX, "asha", "intern")["success"]
    assert not gate.approve_gate(HEX, "  ", "duty_officer")["success"]


def test_reject_blocks_release_and_records_who():
    gate.open_gate(HEX, 90.0, 60.0)
    gate.approve_gate(HEX, "asha", "duty_officer")
    r = gate.reject_gate(HEX, "ravi", "district_authority", "sensor fault")
    assert r["success"] and gate.check_gate(HEX) == "REJECTED"
    assert gate.get_gate_state(HEX)["rejection"]["reason"] == "sensor fault"
    assert not gate.approve_gate(HEX, "meera", "district_authority")["success"]     # no approving a rejected gate


def test_open_gate_does_not_reset_collected_approvals():
    gate.open_gate(HEX, 90.0, 60.0)
    gate.approve_gate(HEX, "asha", "duty_officer")
    gate.open_gate(HEX, 91.0, 61.0)                                    # next cycle re-asserts Red
    assert gate.get_gate_state(HEX)["approvals_count"] == 1


def test_expired_gate_cannot_be_approved(monkeypatch):
    gate.open_gate(HEX, 90.0, 60.0)
    monkeypatch.setattr(gate, "GATE_TIMEOUT_MINUTES", 0)
    assert not gate.approve_gate(HEX, "asha", "duty_officer")["success"]
    assert gate.check_gate(HEX) == "EXPIRED"


def test_http_flow_fires_only_after_second_approval():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.alerts.store import store
    c = TestClient(app)
    with store._lock:
        store._states, store._alerts, store._downgrades = {}, [], []
    c.post("/alert/trigger", json={"hex_id": HEX, "tier": "Red", "risk_score": 95.0, "confidence_score": 80.0})
    a = c.post("/alert/gate/approve", json={"hex_id": HEX, "operator_id": "asha", "role": "duty_officer"})
    assert a.json()["action"] == "held" and not c.get("/alert/feed").json()
    same = c.post("/alert/gate/approve", json={"hex_id": HEX, "operator_id": "asha", "role": "district_authority"})
    assert same.status_code == 400
    b = c.post("/alert/gate/approve", json={"hex_id": HEX, "operator_id": "ravi", "role": "district_authority"})
    assert b.json()["action"] == "fired"
    assert c.post("/alert/gate/reject", json={"hex_id": HEX, "operator_id": "x", "role": "duty_officer"}).status_code == 409
