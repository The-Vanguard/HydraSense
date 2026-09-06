"""
backend/alerts/test_phase11.py — Phase 11
Pytest suite for SRS.md Section 25 Phase 11 acceptance criteria.

All tests use injectable `now` timestamps so dedup timing is deterministic.
Tests run against the module-level `store` singleton; each test resets it
via the `fresh_store` fixture to ensure isolation.

Run:
  python -m pytest backend/alerts/test_phase11.py -v
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Patch the module-level store with a fresh instance before each test
# ---------------------------------------------------------------------------

from backend.alerts import store as store_module
from backend.alerts.store import AlertStore
from backend.alerts import router as router_module
from backend.alerts import fanout as fanout_module
from backend.alerts.dedup import evaluate, is_resolved, COOLDOWN_MINUTES, RESOLVE_CYCLES
from backend.alerts.models import AlertState, AlertRecord, tier_rank
from backend.alerts.cap_generator import generate_cap_xml


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    """Replace the module-level `store` singleton with a fresh instance for each test."""
    new_store = AlertStore()
    monkeypatch.setattr(store_module, "store", new_store)
    monkeypatch.setattr(router_module, "store", new_store)

    # Redirect fanout file output to tmp_path so tests don't pollute the repo
    monkeypatch.setattr(fanout_module, "_DATA_DIR", tmp_path)
    yield new_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


def _state(
    hex_id: str = "8860064e61fffff",
    last_tier: str | None = None,
    last_ts: datetime | None = None,
    cycles: int = 0,
) -> AlertState:
    return AlertState(
        hex_id=hex_id,
        last_alert_tier=last_tier,
        last_alert_timestamp=last_ts,
        consecutive_below_orange_cycles=cycles,
    )


# ===========================================================================
# CAP XML structure tests (SRS §17.3)
# ===========================================================================

class TestCapXmlStructure:
    """CAP 1.2 XML must match SRS §17.3 exactly."""

    def _gen(self, tier="Red", lead_time_min=120, lead_time_basis="forecast_crossing_t+2h"):
        return generate_cap_xml(
            alert_id="HYDRASENSE-WYD-2026-000001",
            hex_id="8860064e61fffff",
            tier=tier,
            risk_score=82,
            confidence_score=88,
            lead_time_min=lead_time_min,
            lead_time_basis=lead_time_basis,
            nearest_shelter={"name": "Meppadi Government School", "distance_m": 3200},
            sent_ist="2026-09-06T14:32:00+05:30",
        )

    def test_cap_xml_is_parseable(self):
        cap_xml, _ = self._gen()
        # Should parse without error
        root = ET.fromstring(cap_xml.replace('<?xml version="1.0" encoding="UTF-8"?>\n', ""))
        assert root.tag is not None

    def test_cap_required_fields_present(self):
        """All §17.3 required fields must be present."""
        cap_xml, _ = self._gen()
        xml_body = cap_xml.replace('<?xml version="1.0" encoding="UTF-8"?>\n', "")
        root = ET.fromstring(xml_body)
        ns = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}

        # Top-level required fields
        assert root.find("identifier") is not None or root.find("c:identifier", ns) is not None
        assert cap_xml.count("<sender>") >= 1 or "sender" in cap_xml
        assert "hydrasense.sih2026@example.org" in cap_xml
        assert "Actual" in cap_xml
        assert "Alert" in cap_xml
        assert "Public" in cap_xml

    def test_cap_identifier_format(self):
        """Identifier must match HYDRASENSE-WYD-YYYY-NNNNNN."""
        _, payload = self._gen()
        ident = payload["identifier"]
        import re
        assert re.match(r"HYDRASENSE-WYD-\d{4}-\d{6}$", ident), \
            f"Identifier '{ident}' does not match HYDRASENSE-WYD-YYYY-NNNNNN"

    def test_cap_severity_red(self):
        _, payload = self._gen(tier="Red")
        assert payload["severity"] == "Severe"

    def test_cap_severity_orange(self):
        _, payload = self._gen(tier="Orange")
        assert payload["severity"] == "Moderate"

    def test_cap_description_contains_risk_score(self):
        _, payload = self._gen()
        assert "82" in payload["description"]

    def test_cap_description_contains_confidence(self):
        _, payload = self._gen()
        assert "88" in payload["description"]

    def test_lead_time_hour_granular_in_description(self):
        """SRS §12: lead_time_min must be hour-granular (multiple of 60)."""
        _, payload = self._gen(lead_time_min=120, lead_time_basis="forecast_crossing_t+2h")
        desc = payload["description"]
        assert "120 minutes" in desc
        assert "2h" in desc

    def test_no_forecast_crossing_honest_string(self):
        """SRS §12: when no crossing, show exact honest string."""
        _, payload = self._gen(
            lead_time_min=None,
            lead_time_basis="no_red_crossing_in_forecast_window"
        )
        desc = payload["description"]
        assert "No Red-tier crossing" in desc

    def test_shelter_in_description(self):
        _, payload = self._gen()
        assert "Meppadi Government School" in payload["description"]

    def test_polygon_present_for_known_hex(self):
        _, payload = self._gen()
        assert payload["polygon"] != "", "Polygon must be non-empty for known pilot hex"

    def test_sent_field_has_ist_offset(self):
        cap_xml, _ = self._gen()
        assert "+05:30" in cap_xml, "CAP <sent> must be in IST (+05:30) per §17.3 example"

    def test_cap_xml_declaration_present(self):
        cap_xml, _ = self._gen()
        assert cap_xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')


# ===========================================================================
# Dedup logic tests (SRS §17.1)
# ===========================================================================

class TestDedupFire:
    """§17.1: fire conditions."""

    def test_first_alert_fires(self):
        """No prior alert for hex → always fire."""
        st = _state()
        decision, _ = evaluate(st, "Red", now=T0)
        assert decision == "fire"

    def test_tier_increase_fires(self):
        """Green→Yellow: Yellow > Green → fire."""
        st = _state(last_tier="Green", last_ts=T0 - timedelta(minutes=5))
        decision, _ = evaluate(st, "Yellow", now=T0)
        assert decision == "fire"

    def test_orange_to_red_fires(self):
        """Orange→Red: tier increase → fire."""
        st = _state(last_tier="Orange", last_ts=T0 - timedelta(minutes=5))
        decision, _ = evaluate(st, "Red", now=T0)
        assert decision == "fire"

    def test_same_tier_within_cooldown_skips(self):
        """§17.1: same tier within 30 min → skip."""
        st = _state(last_tier="Red", last_ts=T0 - timedelta(minutes=10))
        decision, _ = evaluate(st, "Red", now=T0)
        assert decision == "skip"

    def test_same_tier_after_cooldown_fires(self):
        """§17.1: same tier after 30 min → fire again."""
        st = _state(last_tier="Red", last_ts=T0 - timedelta(minutes=COOLDOWN_MINUTES))
        decision, _ = evaluate(st, "Red", now=T0)
        assert decision == "fire"

    def test_fire_updates_last_alert_tier(self):
        st = _state()
        _, updated = evaluate(st, "Orange", now=T0)
        assert updated.last_alert_tier == "Orange"

    def test_fire_updates_last_alert_timestamp(self):
        st = _state()
        _, updated = evaluate(st, "Orange", now=T0)
        assert updated.last_alert_timestamp == T0

    def test_skip_does_not_update_timestamp(self):
        """Skip must not reset the cooldown clock."""
        ts_before = T0 - timedelta(minutes=5)
        st = _state(last_tier="Red", last_ts=ts_before)
        _, updated = evaluate(st, "Red", now=T0)
        assert updated.last_alert_timestamp == ts_before


# ===========================================================================
# Downgrade / recovery tests (SRS §17.2)
# ===========================================================================

class TestDedupDowngrade:
    """§17.2: downgrade and recovery."""

    def test_tier_drop_returns_downgrade(self):
        """Orange→Yellow → downgrade, no CAP."""
        st = _state(last_tier="Orange", last_ts=T0 - timedelta(minutes=5))
        decision, _ = evaluate(st, "Yellow", now=T0)
        assert decision == "downgrade"

    def test_tier_drop_increments_counter(self):
        st = _state(last_tier="Orange", last_ts=T0, cycles=0)
        _, updated = evaluate(st, "Green", now=T0)
        assert updated.consecutive_below_orange_cycles == 1

    def test_one_below_orange_not_resolved(self):
        st = _state(last_tier="Orange", last_ts=T0, cycles=0)
        _, updated = evaluate(st, "Green", now=T0)
        assert not is_resolved(updated)

    def test_two_consecutive_below_orange_resolves(self):
        """§17.2: exactly 2 cycles required for resolved."""
        # First drop
        st = _state(last_tier="Orange", last_ts=T0, cycles=0)
        _, st = evaluate(st, "Green", now=T0)
        # Second drop
        _, st = evaluate(st, "Yellow", now=T0 + timedelta(hours=1))
        assert is_resolved(st)
        assert st.consecutive_below_orange_cycles >= RESOLVE_CYCLES

    def test_orange_resets_counter(self):
        """§17.2: returning to Orange/Red resets consecutive_below_orange_cycles."""
        st = _state(last_tier="Orange", last_ts=T0 - timedelta(hours=1), cycles=1)
        decision, updated = evaluate(st, "Orange", now=T0)
        assert updated.consecutive_below_orange_cycles == 0

    def test_red_also_resets_counter(self):
        st = _state(last_tier="Red", last_ts=T0 - timedelta(hours=1), cycles=1)
        _, updated = evaluate(st, "Red", now=T0)
        assert updated.consecutive_below_orange_cycles == 0

    def test_downgrade_no_cap_on_tier_drop(self):
        """A tier drop must never produce a fire decision."""
        st = _state(last_tier="Red", last_ts=T0, cycles=0)
        decision, _ = evaluate(st, "Yellow", now=T0)
        assert decision == "downgrade"

    def test_green_yellow_both_count_as_below_orange(self):
        """Both Green and Yellow are below Orange and should increment the counter."""
        st = _state(last_tier="Orange", last_ts=T0, cycles=0)
        _, st = evaluate(st, "Green", now=T0)
        assert st.consecutive_below_orange_cycles == 1
        _, st = evaluate(st, "Yellow", now=T0)
        assert st.consecutive_below_orange_cycles == 2
        assert is_resolved(st)


# ===========================================================================
# Alert feed: distinct types (SRS §17)
# ===========================================================================

class TestAlertFeedDistinctTypes:
    """GET /alert/feed must return CAP and downgrade as distinct `type` values."""

    def test_cap_alert_type_is_cap(self, fresh_store):
        record = AlertRecord(
            alert_id="HYDRASENSE-WYD-2026-000001",
            hex_id="8860064e61fffff",
            timestamp=T0,
            tier="Red",
            risk_score=82,
            confidence_score=88,
            lead_time_min=120,
            lead_time_basis="forecast_crossing_t+2h",
            cap_xml="<alert/>",
            cap_payload={},
            delivered_channels=["dashboard"],
            type="cap",
        )
        fresh_store.append_alert(record)
        feed = fresh_store.get_feed()
        assert any(item["type"] == "cap" for item in feed)

    def test_downgrade_type_is_downgrade(self, fresh_store):
        from backend.alerts.models import DowngradeEvent
        ev = DowngradeEvent(
            event_id="DOWNGRADE-xxx-1",
            hex_id="8860064e61fffff",
            timestamp=T0,
            from_tier="Orange",
            to_tier="Yellow",
            resolved=False,
        )
        fresh_store.append_downgrade(ev)
        feed = fresh_store.get_feed()
        assert any(item["type"] == "downgrade" for item in feed)

    def test_feed_contains_both_types(self, fresh_store):
        from backend.alerts.models import DowngradeEvent
        record = AlertRecord(
            alert_id="HYDRASENSE-WYD-2026-000001",
            hex_id="8860064e61fffff",
            timestamp=T0,
            tier="Red",
            risk_score=82,
            confidence_score=88,
            lead_time_min=120,
            lead_time_basis="forecast_crossing_t+2h",
            cap_xml="<alert/>",
            cap_payload={},
        )
        ev = DowngradeEvent(
            event_id="DOWNGRADE-xxx-1",
            hex_id="8860064e61fffff",
            timestamp=T0 + timedelta(minutes=30),
            from_tier="Red",
            to_tier="Yellow",
        )
        fresh_store.append_alert(record)
        fresh_store.append_downgrade(ev)
        feed = fresh_store.get_feed()
        types = {item["type"] for item in feed}
        assert "cap" in types
        assert "downgrade" in types


# ===========================================================================
# Fanout / logging tests (SRS §17 delivery channels)
# ===========================================================================

class TestFanout:
    """Mock channels must write files; never silent."""

    def _record(self):
        return AlertRecord(
            alert_id="HYDRASENSE-WYD-2026-000001",
            hex_id="8860064e61fffff",
            timestamp=T0,
            tier="Red",
            risk_score=82,
            confidence_score=88,
            lead_time_min=120,
            lead_time_basis="forecast_crossing_t+2h",
            cap_xml="<alert/>",
            cap_payload={"nearest_shelter": {"name": "Test Shelter", "distance_m": 1000}},
        )

    def test_sachet_log_written(self, tmp_path):
        from backend.alerts.fanout import post_sachet_mock
        record = self._record()
        result = post_sachet_mock(record)
        assert result is True
        log_file = tmp_path / "sachet_webhook_log.jsonl"
        assert log_file.exists(), "sachet_webhook_log.jsonl must be created on alert fire"
        line = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert line["alert_id"] == record.alert_id

    def test_sachet_log_labeled_mock(self, tmp_path):
        """Must be labeled [MOCK-SACHET] — never a silent stub."""
        from backend.alerts.fanout import post_sachet_mock
        post_sachet_mock(self._record())
        log_file = tmp_path / "sachet_webhook_log.jsonl"
        content = log_file.read_text(encoding="utf-8")
        assert "[MOCK-SACHET]" in content, \
            "Sachet log must contain [MOCK-SACHET] label per CLAUDE.md 'never silent mock' rule"

    def test_sms_log_written(self, tmp_path):
        from backend.alerts.fanout import log_sms
        record = self._record()
        result = log_sms(record)
        assert result is True
        sms_file = tmp_path / "sms_log.txt"
        assert sms_file.exists(), "sms_log.txt must be created on alert fire"
        content = sms_file.read_text(encoding="utf-8")
        assert record.alert_id in content

    def test_sms_log_labeled_mock(self, tmp_path):
        from backend.alerts.fanout import log_sms
        log_sms(self._record())
        sms_file = tmp_path / "sms_log.txt"
        content = sms_file.read_text(encoding="utf-8")
        assert "[MOCK-SMS]" in content

    def test_fanout_returns_delivered_channels(self, tmp_path):
        from backend.alerts.fanout import fanout
        delivered = fanout(self._record())
        assert "dashboard"    in delivered
        assert "sachet_mock"  in delivered
        assert "sms_mock"     in delivered


# ===========================================================================
# Tier ordering sanity
# ===========================================================================

class TestTierOrdering:
    def test_tier_order_green_lowest(self):
        assert tier_rank("Green") < tier_rank("Yellow")

    def test_tier_order_red_highest(self):
        assert tier_rank("Red") > tier_rank("Orange")

    def test_tier_order_full_chain(self):
        assert tier_rank("Green") < tier_rank("Yellow") < tier_rank("Orange") < tier_rank("Red")
