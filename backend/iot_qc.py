"""
backend/iot_qc.py -- sensor QC, node health, sensor-snapping and edge rule (v2 Sec. 12.2).

  QC       range, spike, stuck value, rate of change, temperature compensation, salinity /
           over-read flag, air-gap flag, cross-check against a reference (satellite soil moisture,
           nearby gauge).  A reading that fails QC is NEVER used as ground truth.
  Health   healthy / degraded / offline; feeds C_in (backend/confidence.py) and the fallback chain.
  Snapping a healthy node overrides the gridded value inside its own hex, decaying to zero at
           SNAP_RADIUS_M inside the same micro-catchment; other catchments get no influence.
  Edge     on-device rule -> siren + SMS, calibrated from the fitted I-D threshold + safety margin.

Every numeric threshold here is PROVISIONAL (v2: per-site tuning, gravimetric per-node calibration
before deployment).  They are exposed in `PROVISIONAL_CONSTANTS` and returned in results.
Pure functions; no database, no network.  Nothing here is a sensor driver: readings are inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Optional, Sequence

# metric -> (min, max, max abs change between consecutive readings, minutes-normalised not used)
RANGES = {
    "rain_1h_mm": (0.0, 200.0),
    "soil_moisture_vwc": (0.0, 0.70),         # m3/m3
    "soil_temp_c": (-10.0, 60.0),
    "stage_m": (0.0, 20.0),
    "tilt_deg": (0.0, 90.0),
}
MAX_STEP = {"soil_moisture_vwc": 0.10, "stage_m": 1.5, "soil_temp_c": 8.0, "tilt_deg": 5.0, "rain_1h_mm": 100.0}
SPIKE_MAD_K = 6.0                 # |x - median| > K * max(MAD, floor)
SPIKE_FLOOR = {"soil_moisture_vwc": 0.01, "stage_m": 0.05, "soil_temp_c": 0.5, "tilt_deg": 0.1, "rain_1h_mm": 1.0}
STUCK_N = 6                       # identical consecutive values (only for metrics that must vary)
NEVER_STUCK = {"rain_1h_mm", "tilt_deg"}       # zero rain / zero tilt for hours is normal
TEMP_COEF_PER_C = 0.0008          # m3/m3 per deg C of apparent drift, reference 25 C (provisional)
REF_TEMP_C = 25.0
OVERREAD_THETA = 0.45             # persistently this wet with no rain response -> salinity / over-read
OVERREAD_MIN_READINGS = 12
OVERREAD_MAX_RAIN_MM = 1.0
AIRGAP_STEP = 0.15                # sudden single-step drop in theta (m3/m3)
TWO_DEPTH_DISAGREE = 0.25
REFERENCE_DISAGREE = 0.25         # |node - satellite| in theta
OFFLINE_AFTER = timedelta(minutes=30)
LOW_BATTERY_PCT = 20.0
DEGRADED_FAIL_FRACTION = 0.30     # of the last readings failing QC
SNAP_RADIUS_M = 1500.0            # ~1.5 km, tuned per site
EDGE_SAFETY_MARGIN = 0.8          # threshold = fitted I-D value x margin

PROVISIONAL_CONSTANTS = ("ranges", "max_step", "spike_mad_k", "stuck_n", "temp_coef_per_c",
                         "overread_theta", "airgap_step", "two_depth_disagree", "reference_disagree",
                         "offline_after", "low_battery_pct", "degraded_fail_fraction",
                         "snap_radius_m", "edge_safety_margin")


@dataclass
class QCResult:
    ok: bool
    flags: list = field(default_factory=list)          # any of: range, spike, stuck, rate, airgap, ...
    value: Optional[float] = None                      # temperature-compensated value when applicable


def compensate_theta(theta: float, temp_c: Optional[float]) -> float:
    """Remove the apparent temperature drift of a capacitive probe (reference 25 C)."""
    if temp_c is None:
        return theta
    return theta - TEMP_COEF_PER_C * (temp_c - REF_TEMP_C)


def qc_reading(metric: str, value: Optional[float], history: Sequence[float] = (),
               temp_c: Optional[float] = None) -> QCResult:
    """Range / spike / stuck / rate-of-change checks against the node's own recent history."""
    flags: list[str] = []
    if value is None or value != value:
        return QCResult(False, ["missing"], None)
    lo, hi = RANGES.get(metric, (float("-inf"), float("inf")))
    if not (lo <= value <= hi):
        flags.append("range")
    hist = [h for h in history if h is not None and h == h]
    if len(hist) >= 3 and metric in SPIKE_FLOOR:
        med = median(hist)
        mad = median([abs(h - med) for h in hist])
        if abs(value - med) > SPIKE_MAD_K * max(mad, SPIKE_FLOOR[metric]):
            flags.append("spike")
    if hist and metric in MAX_STEP and abs(value - hist[-1]) > MAX_STEP[metric]:
        flags.append("rate")
    if metric not in NEVER_STUCK and len(hist) >= STUCK_N - 1 and \
            all(h == value for h in hist[-(STUCK_N - 1):]):
        flags.append("stuck")
    out = compensate_theta(value, temp_c) if metric == "soil_moisture_vwc" else value
    return QCResult(not flags, flags, out)


def soil_moisture_flags(theta_series: Sequence[float], rain_mm_recent: float,
                        theta_deep: Optional[float] = None,
                        reference_theta: Optional[float] = None) -> list[str]:
    """
    Sensor-physics flags for a soil-moisture node (v2 Sec. 12.2):
      overread     persistently high theta with no rain response  -> salinity / over-read
      airgap       sudden single-step drop, or two depths disagreeing with no rain -> lost contact
      reference    disagrees with the independent (satellite / gridded) soil moisture
    """
    flags = []
    s = [x for x in theta_series if x == x]
    if len(s) >= OVERREAD_MIN_READINGS and min(s[-OVERREAD_MIN_READINGS:]) >= OVERREAD_THETA \
            and rain_mm_recent < OVERREAD_MAX_RAIN_MM:
        flags.append("overread")
    if len(s) >= 2 and (s[-2] - s[-1]) >= AIRGAP_STEP:
        flags.append("airgap")
    if theta_deep is not None and s and abs(s[-1] - theta_deep) > TWO_DEPTH_DISAGREE and rain_mm_recent < 1.0:
        flags.append("airgap")
    if reference_theta is not None and s and abs(s[-1] - reference_theta) > REFERENCE_DISAGREE:
        flags.append("reference")
    return sorted(set(flags))


def node_health(now: datetime, last_seen: Optional[datetime], battery_pct: Optional[float],
                recent_qc_ok: Sequence[bool], persistent_flags: Sequence[str] = ()) -> str:
    """'offline' | 'degraded' | 'healthy'.  A degraded node falls to Tier 1 in the fallback chain."""
    if last_seen is None or now - last_seen > OFFLINE_AFTER:
        return "offline"
    fails = (1 - sum(recent_qc_ok) / len(recent_qc_ok)) if recent_qc_ok else 0.0
    if (battery_pct is not None and battery_pct < LOW_BATTERY_PCT) or fails >= DEGRADED_FAIL_FRACTION \
            or any(f in ("overread", "airgap", "reference") for f in persistent_flags):
        return "degraded"
    return "healthy"


def snap_weight(distance_m: float, same_hex: bool, same_catchment: bool,
                radius_m: float = SNAP_RADIUS_M) -> float:
    """1.0 inside the node's own hex; inside the same micro-catchment decays linearly to 0 at
    radius_m; 0 for other catchments (no influence across a divide)."""
    if same_hex:
        return 1.0
    if not same_catchment or distance_m >= radius_m:
        return 0.0
    return max(0.0, 1.0 - distance_m / radius_m)


def snapped_value(node_value: Optional[float], grid_value: float, weight: float, health: str) -> tuple[float, bool]:
    """Blend node and gridded value.  Only a HEALTHY node with weight > 0 counts; returns
    (value, sensor_adjusted)."""
    if node_value is None or health != "healthy" or weight <= 0.0:
        return grid_value, False
    return weight * node_value + (1.0 - weight) * grid_value, True


def edge_thresholds_from_id(alpha: float, beta: float, safety: float = EDGE_SAFETY_MARGIN) -> dict:
    """tau_int (1 h intensity, mm/h) and tau_acc (24 h accumulation, mm) from a fitted I-D
    threshold I = alpha * D**-beta, times a safety margin (<1 = alarm earlier than the threshold)."""
    return dict(tau_int_mm_h=alpha * 1.0 ** (-beta) * safety,
                tau_acc_mm=alpha * 24.0 ** (-beta) * 24.0 * safety)


def edge_alarm(rain_1h: float, rain_24h: float, theta: float, tilt_rate_deg_h: float,
               tau_int: float, tau_acc: float, theta_crit: float, tau_tilt: float) -> dict:
    """
    On-device rule (v2 Sec. 12.2):
        rain_1h >= tau_int  OR  (rain_24h >= tau_acc AND theta >= theta_crit)  OR  tilt_rate >= tau_tilt
    Simpler and less accurate than the fusion model by design: it trades accuracy for availability.
    """
    reasons = []
    if rain_1h >= tau_int:
        reasons.append("intensity")
    if rain_24h >= tau_acc and theta >= theta_crit:
        reasons.append("accumulation_and_wet_soil")
    if tilt_rate_deg_h >= tau_tilt:
        reasons.append("tilt")
    return dict(alarm=bool(reasons), reasons=reasons)
