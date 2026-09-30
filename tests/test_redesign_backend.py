"""tests/test_redesign_backend.py -- KPI summary, region peak rainfall and per-hazard history fields."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import village_cycle as vc  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers import village as vapi  # noqa: E402


def test_village_summary_counts_unscored_separately(monkeypatch, tmp_path):
    for code in ("aa-x", "bb-y"):
        (tmp_path / f"{code}.gpkg").write_text("")
    monkeypatch.setattr(vapi, "GPKG_DIR", tmp_path)
    fake = {
        "aa-x": dict(villages=5, scored=3, tier_counts={"Red": 1, "Orange": 0, "Yellow": 1, "Green": 1},
                     top_village=dict(village_id="v1", name="A", alert_tier="Red", alert_value=80.0)),
        "bb-y": dict(villages=2, scored=2, tier_counts={"Red": 0, "Orange": 1, "Yellow": 0, "Green": 1},
                     top_village=dict(village_id="v9", name="B", alert_tier="Orange", alert_value=60.0)),
    }
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(vc, "SUMMARY", {k: dict(v, at=now) for k, v in fake.items()})
    d = TestClient(app).get("/village/summary").json()
    assert d["tier_counts"] == {"Red": 1, "Orange": 1, "Yellow": 1, "Green": 2}
    assert d["villages"] == 7 and d["scored_villages"] == 5 and d["unscored_villages"] == 2
    assert d["top_village"]["name"] == "A" and d["top_village"]["region_code"] == "aa-x"
    one = TestClient(app).get("/village/summary", params={"region": "bb-y"}).json()
    assert one["tier_counts"]["Orange"] == 1 and one["villages"] == 2


def test_history_model_has_optional_hazard_fields():
    from backend.models import RiskHistoryEntry
    e = RiskHistoryEntry(timestamp="t", risk_score=1.0, tier="Green")
    assert e.index_flood is None and e.index_landslide is None and e.rainfall_24h is None
