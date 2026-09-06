"""
backend/alerts/fanout.py — Phase 11
Routes a fired alert to three channels per SRS.md Section 17:
  1. Mock "Sachet-compatible" webhook  — logs to data/alerts/sachet_webhook_log.jsonl
  2. Simulated SMS log               — appends to data/alerts/sms_log.txt
  3. Dashboard alert feed            — done by router.py (store.append_alert)

CLAUDE.md constraint: every external-style call must have a timeout + visible fallback label,
never a silent mock standing in for real data. Both functions log failures explicitly.

SRS §17 note: "Do not attempt to integrate with a real Sachet endpoint — none exists publicly.
The mock webhook is the correct and final implementation for this build."
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import AlertRecord

logger = logging.getLogger(__name__)

# Output directory — created on first write
_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "alerts"


def _ensure_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Mock Sachet-compatible webhook (SRS §17 — final impl, not a placeholder)
# ---------------------------------------------------------------------------

def post_sachet_mock(alert: AlertRecord) -> bool:
    """
    Writes the CAP payload to sachet_webhook_log.jsonl.
    Returns True on success, False on failure.
    Labeled [MOCK-SACHET] in logs — never a silent stub.

    Timeout: N/A (local file write). If file write fails, logs the error and
    returns False — caller adds "sachet_mock" to delivered_channels only on True.
    """
    _ensure_dir()
    log_path = _DATA_DIR / "sachet_webhook_log.jsonl"
    entry = {
        "channel":    "[MOCK-SACHET] — no real Sachet endpoint exists (SRS §17)",
        "alert_id":   alert.alert_id,
        "hex_id":     alert.hex_id,
        "tier":       alert.tier,
        "risk_score": alert.risk_score,
        "sent_utc":   datetime.now(timezone.utc).isoformat(),
        "cap_payload": alert.cap_payload,
    }
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("[MOCK-SACHET] alert %s logged to %s", alert.alert_id, log_path)
        return True
    except OSError as exc:
        logger.error("[MOCK-SACHET] FAILED to write %s: %s", log_path, exc)
        return False


# ---------------------------------------------------------------------------
# 2. Simulated SMS log
# ---------------------------------------------------------------------------

def log_sms(alert: AlertRecord) -> bool:
    """
    Appends a plain-text SMS-style row to sms_log.txt.
    Returns True on success, False on failure.
    Labeled [MOCK-SMS] — never silent.
    """
    _ensure_dir()
    log_path = _DATA_DIR / "sms_log.txt"

    lead_text = (
        f"Lead time: {alert.lead_time_min} min"
        if alert.lead_time_min is not None
        else "No Red crossing in forecast window"
    )
    shelter = alert.cap_payload.get("nearest_shelter") or {}
    shelter_name = shelter.get("name", "see district authority")

    sms_text = (
        f"[MOCK-SMS] {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | "
        f"HYDRASENSE ALERT | Hex {alert.hex_id} | Tier: {alert.tier} | "
        f"Risk: {int(alert.risk_score)}/100 | Confidence: {int(alert.confidence_score)}/100 | "
        f"{lead_text} | Shelter: {shelter_name} | ID: {alert.alert_id}"
    )
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(sms_text + "\n")
        logger.info("[MOCK-SMS] alert %s logged to %s", alert.alert_id, log_path)
        return True
    except OSError as exc:
        logger.error("[MOCK-SMS] FAILED to write %s: %s", log_path, exc)
        return False


# ---------------------------------------------------------------------------
# 3. Fan out to all channels; return list of delivered channel names
# ---------------------------------------------------------------------------

def fanout(alert: AlertRecord) -> list[str]:
    """
    Calls all delivery channels. Returns list of successfully delivered channels.
    Always adds "dashboard" (store.append_alert is called by router.py before fanout).
    """
    delivered: list[str] = ["dashboard"]

    if post_sachet_mock(alert):
        delivered.append("sachet_mock")

    if log_sms(alert):
        delivered.append("sms_mock")

    return delivered
