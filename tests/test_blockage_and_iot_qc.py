"""tests/test_blockage_and_iot_qc.py -- E4 blockage check (v2 7.4) and sensor QC / snapping / edge rule (v2 12.2)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import blockage as bk   # noqa: E402
from backend import iot_qc as qc     # noqa: E402
from backend.classifier import classify_trigger  # noqa: E402

NOW = datetime(2026, 9, 30, 12, 0)


def series(start_m, end_m, n=5, minutes=25):
    """n readings over the last `minutes`, moving linearly from start_m to end_m."""
    return [(NOW - timedelta(minutes=minutes) + timedelta(minutes=minutes * i / (n - 1)),
             start_m + (end_m - start_m) * i / (n - 1)) for i in range(n)]


# ---------------------------------------------------------------- E4
def test_no_sensors_means_off_not_clear():
    r = bk.check_blockage(None, series(1, 1), "Red", NOW)
    assert r["status"] == "off_no_sensors" and r["blockage_suspect"] is False
    assert bk.check_blockage(series(1, 1), [], "Red", NOW)["status"] == "off_no_sensors"


def test_blockage_pattern_detected_and_feeds_classifier():
    r = bk.check_blockage(upstream=series(1.0, 1.6), downstream=series(1.2, 0.6),
                          upstream_landslide_tier="Orange", now=NOW)
    assert r["status"] == "blockage_suspect" and r["trigger_type"] == "LANDSLIDE_DAM"
    assert classify_trigger(r_int=0, m=0.9, flood_indicator=0, r_acc=0, flood_head_level="Green",
                            p_fs_lt1=0.9, landslide_head_level="Orange", rain_persisting=True,
                            blockage_suspect=r["blockage_suspect"]) == "LANDSLIDE_DAM"


def test_tilt_alarm_can_replace_the_landslide_tier():
    r = bk.check_blockage(series(1.0, 1.6), series(1.2, 0.6), "Green", NOW, node_tilt_alarm=True)
    assert r["blockage_suspect"] is True


def test_stage_pattern_without_slide_trigger_is_clear():
    r = bk.check_blockage(series(1.0, 1.6), series(1.2, 0.6), "Yellow", NOW)
    assert r["status"] == "clear" and r["evidence"]["stage_pattern"] is True


def test_slide_without_stage_pattern_is_clear():
    r = bk.check_blockage(series(1.0, 1.05), series(1.2, 1.18), "Red", NOW)
    assert r["status"] == "clear"


def test_both_rising_is_a_flood_not_a_blockage():
    assert bk.check_blockage(series(1, 1.6), series(1, 1.6), "Red", NOW)["blockage_suspect"] is False


def test_too_few_readings_is_insufficient_not_clear():
    r = bk.check_blockage(series(1, 1.6, n=2), series(1.2, 0.6), "Red", NOW)
    assert r["status"] == "insufficient_data" and r["blockage_suspect"] is False


def test_old_readings_outside_window_are_ignored():
    old = [(NOW - timedelta(hours=3, minutes=i), 1.0) for i in range(5)]
    assert bk.check_blockage(old, series(1.2, 0.6), "Red", NOW)["status"] == "insufficient_data"


def test_blocked_road_segments_flagged():
    assert bk.flag_blocked_segments(["r1", "r2", "r3"], ["r2"]) == ["r2"]


def test_constants_reported_as_provisional():
    assert "delta_h_down_m" in bk.check_blockage(None, None, None, NOW)["provisional_constants"]


# ---------------------------------------------------------------- QC
def test_range_missing_and_spike():
    assert qc.qc_reading("soil_moisture_vwc", 0.9).flags == ["range"]
    assert qc.qc_reading("soil_moisture_vwc", None).flags == ["missing"]
    hist = [0.30, 0.31, 0.30, 0.31, 0.30]
    assert "spike" in qc.qc_reading("soil_moisture_vwc", 0.55, hist).flags
    assert qc.qc_reading("soil_moisture_vwc", 0.32, hist).ok


def test_rate_of_change_flag():
    assert "rate" in qc.qc_reading("soil_moisture_vwc", 0.50, [0.30]).flags


def test_stuck_value_flagged_but_zero_rain_is_normal():
    assert "stuck" in qc.qc_reading("soil_moisture_vwc", 0.31, [0.31] * 5).flags
    assert qc.qc_reading("rain_1h_mm", 0.0, [0.0] * 20).ok
    assert qc.qc_reading("tilt_deg", 0.0, [0.0] * 20).ok


def test_temperature_compensation_removes_drift_only_for_soil_moisture():
    warm = qc.qc_reading("soil_moisture_vwc", 0.40, [0.40], temp_c=35.0).value
    assert warm == pytest.approx(0.40 - qc.TEMP_COEF_PER_C * 10)
    assert qc.qc_reading("soil_moisture_vwc", 0.40, [0.40], temp_c=25.0).value == pytest.approx(0.40)
    assert qc.qc_reading("stage_m", 2.0, [2.0], temp_c=35.0).value == 2.0


def test_overread_airgap_and_reference_flags():
    wet = [0.5] * 12
    assert "overread" in qc.soil_moisture_flags(wet, rain_mm_recent=0.0)
    assert "overread" not in qc.soil_moisture_flags(wet, rain_mm_recent=30.0)      # rain explains it
    assert "airgap" in qc.soil_moisture_flags([0.40, 0.20], 0.0)                   # step drop
    assert "airgap" in qc.soil_moisture_flags([0.40], 0.0, theta_deep=0.05)        # two depths disagree
    assert "reference" in qc.soil_moisture_flags([0.40], 5.0, reference_theta=0.05)
    assert qc.soil_moisture_flags([0.30, 0.31], 5.0, theta_deep=0.32, reference_theta=0.30) == []


# ---------------------------------------------------------------- health + snapping
def test_node_health_states():
    seen = NOW - timedelta(minutes=5)
    assert qc.node_health(NOW, seen, 80, [True] * 10) == "healthy"
    assert qc.node_health(NOW, None, 80, [True] * 10) == "offline"
    assert qc.node_health(NOW, NOW - timedelta(hours=2), 80, [True] * 10) == "offline"
    assert qc.node_health(NOW, seen, 10, [True] * 10) == "degraded"                # low battery
    assert qc.node_health(NOW, seen, 80, [True] * 6 + [False] * 4) == "degraded"   # 40% failing QC
    assert qc.node_health(NOW, seen, 80, [True] * 10, ["overread"]) == "degraded"


def test_snap_weight_decay_and_catchment_gate():
    assert qc.snap_weight(0, True, True) == 1.0
    assert qc.snap_weight(750, False, True) == pytest.approx(0.5)
    assert qc.snap_weight(1500, False, True) == 0.0
    assert qc.snap_weight(100, False, False) == 0.0            # other catchment: no influence


def test_only_healthy_nodes_snap():
    v, adj = qc.snapped_value(0.6, 0.3, 1.0, "healthy")
    assert (v, adj) == (0.6, True)
    v, adj = qc.snapped_value(0.6, 0.3, 0.5, "healthy")
    assert v == pytest.approx(0.45) and adj is True
    for bad in ("degraded", "offline"):
        assert qc.snapped_value(0.6, 0.3, 1.0, bad) == (0.3, False)
    assert qc.snapped_value(None, 0.3, 1.0, "healthy") == (0.3, False)


# ---------------------------------------------------------------- edge rule
def test_edge_thresholds_from_fitted_id():
    t = qc.edge_thresholds_from_id(alpha=14.82, beta=0.39, safety=0.8)
    assert t["tau_int_mm_h"] == pytest.approx(14.82 * 0.8)
    assert t["tau_acc_mm"] == pytest.approx(14.82 * 24 ** -0.39 * 24 * 0.8)


def test_edge_alarm_rules():
    kw = dict(tau_int=12, tau_acc=150, theta_crit=0.4, tau_tilt=1.0)
    assert qc.edge_alarm(15, 20, 0.2, 0, **kw) == dict(alarm=True, reasons=["intensity"])
    assert qc.edge_alarm(2, 200, 0.45, 0, **kw)["reasons"] == ["accumulation_and_wet_soil"]
    assert qc.edge_alarm(2, 200, 0.20, 0, **kw)["alarm"] is False          # big rain but dry soil
    assert qc.edge_alarm(0, 0, 0.1, 2.0, **kw)["reasons"] == ["tilt"]
    assert qc.edge_alarm(2, 20, 0.2, 0.1, **kw)["alarm"] is False
