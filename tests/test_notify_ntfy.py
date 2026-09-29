"""tests/test_notify_ntfy.py -- push is opt-in (NTFY_TOPIC) and never contacts ntfy.sh when unset."""
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import notify_ntfy as nt  # noqa: E402


class _Resp:
    status_code = 200
    def raise_for_status(self):  # noqa: E301
        return None


def test_no_topic_means_no_network_call(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.setattr(nt.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))
    out = nt.send_ntfy_alert("t", "m", "Red")
    assert out["sent"] is False and "DISABLED" in out["detail"] and "nothing was sent" in out["detail"]


def test_blank_topic_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "   ")
    monkeypatch.setattr(nt.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))
    assert nt.send_ntfy_alert("t", "m", "Orange")["sent"] is False


def test_topic_from_env_is_used(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "my-private-topic")
    seen = {}

    def fake_post(url, **kw):
        seen["url"], seen["prio"] = url, kw["headers"]["Priority"]
        return _Resp()
    monkeypatch.setattr(nt.httpx, "post", fake_post)
    out = nt.send_ntfy_alert("t", "m", "Red")
    assert out["sent"] is True and seen["url"] == "https://ntfy.sh/my-private-topic" and seen["prio"] == "urgent"


def test_network_failure_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "x")
    monkeypatch.setattr(nt.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("boom")))
    out = nt.send_ntfy_alert("t", "m", "Red")
    assert out["sent"] is False and "NOT delivered" in out["detail"]
