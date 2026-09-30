"""
tests/test_phase7_alerts.py

Tests Phase 7: Governed alerting, two-person authorization.
"""
import sys
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.main import app
from backend.alerts.gate import _GATE_STATE_PATH
from backend.alerts.store import store

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_stores():
    """Reset JSON stores and memory before and after tests."""
    def _reset():
        if _GATE_STATE_PATH.exists():
            _GATE_STATE_PATH.unlink()
        with store._lock:
            store._states = {}
            store._alerts = []
            store._downgrades = []
            store._counter = 0
            store._downgrade_counter = 0
    
    _reset()
    yield
    _reset()

def test_trigger_orange_held_for_gate():
    """Orange alerts should be HELD, not fired immediately."""
    req = {
        "hex_id": "8860064e61fffff",
        "tier": "Orange",
        "risk_score": 85.0,
        "confidence_score": 90.0,
        "lead_time_min": 120
    }
    
    resp = client.post("/alert/trigger", json=req)
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "held"
    assert "Pending two-person authorization" in data["reason"]

def test_approve_held_alert():
    """Approving an alert should fire it."""
    # 1. Trigger
    hex_id = "8860064e61fffff"
    client.post("/alert/trigger", json={
        "hex_id": hex_id,
        "tier": "Red",
        "risk_score": 95.0,
        "confidence_score": 90.0
    })
    
    # 2. Approve
    approve_req = {
        "hex_id": hex_id,
        "operator_id": "admin_01",
        "tier": "Red",
        "risk_score": 95.0,
        "confidence_score": 90.0
    }
    
    first = client.post("/alert/gate/approve", json=approve_req)      # 1/2: nothing is sent yet
    assert first.status_code == 200 and first.json()["action"] == "held"
    resp = client.post("/alert/gate/approve", json={**approve_req, "operator_id": "authority_01",
                                                     "role": "district_authority"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "fired"
    assert "alert_id" in data

def test_trigger_specific_cap_template():
    """Verify that the CAP XML includes trigger-specific descriptions."""
    hex_id = "8860064e61fffff"
    client.post("/alert/trigger", json={
        "hex_id": hex_id, "tier": "Red", "risk_score": 95.0, "confidence_score": 90.0
    })
    
    client.post("/alert/gate/approve", json={"hex_id": hex_id, "operator_id": "duty", "role": "duty_officer"})
    resp = client.post("/alert/gate/approve", json={
        "hex_id": hex_id, "operator_id": "admin", "role": "district_authority", "tier": "Red",
        "risk_score": 95.0, "confidence_score": 90.0,
        "trigger_type": "CLOUDBURST_FLASH"
    })
    
    assert resp.status_code == 200
    alert_id = resp.json()["alert_id"]
    
    feed = client.get("/alert/feed").json()
    alert = next(a for a in feed if a.get("alert_id") == alert_id)
    
    assert "CLOUDBURST_FLASH" in alert["cap_payload"]["headline"]
    assert "Leave stream banks/low ground now." in alert["cap_payload"]["description"]
