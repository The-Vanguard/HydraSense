"""tests/test_demo_perf_and_honesty.py -- coarse weather cache + the risk endpoint serving stored scores
without invented factor-of-safety values."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.coarse_cache import coarse_cached  # noqa: E402
from backend.models import RiskResponse  # noqa: E402


def test_same_coarse_cell_shares_one_fetch_and_far_cells_do_not():
    calls = []

    @coarse_cached(ttl_s=60, cell_deg=0.1)
    def fetch(lat, lon, hours=72):
        calls.append((lat, lon))
        return {"ok": True}, "live"
    fetch(11.501, 76.101); fetch(11.512, 76.109); fetch(11.499, 76.095)       # one 0.1 degree cell
    assert len(calls) == 1
    fetch(11.75, 76.15)                                                       # a different cell
    assert len(calls) == 2
    fetch(11.501, 76.101, hours=24)                                           # different arguments
    assert len(calls) == 3


def test_failures_and_fallbacks_are_never_cached():
    calls = []

    @coarse_cached(ttl_s=60, success=lambda r: r[1] == "live")
    def fetch(lat, lon):
        calls.append(1)
        return {}, "cached_demo" if len(calls) == 1 else "live"
    assert fetch(1.0, 1.0)[1] == "cached_demo"
    assert fetch(1.0, 1.0)[1] == "live"                                       # retried the live source
    assert fetch(1.0, 1.0)[1] == "live" and len(calls) == 2                   # now cached


def test_entries_expire(monkeypatch):
    import backend.coarse_cache as cc
    now = [1000.0]
    monkeypatch.setattr(cc.time, "time", lambda: now[0])
    calls = []

    @coarse_cached(ttl_s=10)
    def fetch(lat, lon):
        calls.append(1)
        return 1
    fetch(0.0, 0.0); fetch(0.0, 0.0)
    now[0] += 11
    fetch(0.0, 0.0)
    assert len(calls) == 2


def test_risk_response_no_longer_invents_factor_of_safety():
    r = RiskResponse(hex_id="h", timestamp="t", risk_score=1.0, tier="Green", confidence_score=50.0)
    assert r.factor_of_safety is None and r.factor_of_safety_min is None and r.factor_of_safety_max is None


def test_cached_endpoint_returns_real_fs_from_memory_or_none(monkeypatch):
    """A fresh stored row is served without recomputing; FS is the model's own value or None."""
    import sqlite3
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from backend import risk_engine
    from backend.routers import risk as risk_api

    ts = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE risk_scores (id INTEGER PRIMARY KEY, hex_id TEXT, timestamp TEXT, risk_score REAL, "
                 "tier TEXT, confidence_score REAL, lead_time_min INT, lead_time_basis TEXT, "
                 "feature_contributions TEXT, data_source TEXT, sensor_adjusted INT)")
    conn.execute("INSERT INTO risk_scores VALUES (1,'h1',?,12.0,'Green',40.0,NULL,'x','[]','open_meteo_live',0)", (ts,))

    @contextmanager
    def fake_db():
        yield conn
    monkeypatch.setattr(risk_api, "get_db", fake_db)
    monkeypatch.setattr(risk_api, "compute_and_store_risk", lambda h: (_ for _ in ()).throw(AssertionError("recomputed")))
    monkeypatch.setattr(risk_engine, "LAST_RESULTS", {})
    out = risk_api.get_risk("h1")                                  # no in-memory copy -> FS is None, not 0.96
    assert out.factor_of_safety is None and out.risk_score == 12.0
    risk_engine.LAST_RESULTS["h1"] = dict(hex_id="h1", timestamp=ts, risk_score=12.0, tier="Green",
                                          confidence_score=40.0, factor_of_safety=1.7,
                                          factor_of_safety_min=1.4, factor_of_safety_max=2.0)
    assert risk_api.get_risk("h1").factor_of_safety == 1.7         # real value from this process
