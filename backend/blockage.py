"""
backend/blockage.py -- E4 stream-blockage / dam-formation check (v2 Sec. 7.4).

    blockage_suspect =
        landslide head >= Orange in the upstream catchment  (or a node tilt alarm)
        AND downstream stage falling >= DELTA_H_DOWN over the window
        AND upstream   stage rising  >= DELTA_H_UP   over the window

Runs ONLY where a paired upstream / downstream stage sensor exists (or a CWC gauge on the reach).
Otherwise the check is OFF and says so: it never guesses.  A sensor that fails QC or has too few
readings in the window yields "insufficient_data", never "clear".

The stage-change thresholds and window are initial values (v2: "tuned in back-tests") and are
returned with every result as provisional.  Output feeds the trigger classifier
(`blockage_suspect` -> LANDSLIDE_DAM) and flags road segments on the blocked reach (Sec. 11).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional, Sequence, Tuple

DELTA_H_DOWN_M = 0.30          # downstream stage must FALL at least this much   (provisional)
DELTA_H_UP_M = 0.30            # upstream stage must RISE at least this much     (provisional)
WINDOW = timedelta(minutes=30)  # comparison window                                (provisional)
MIN_READINGS = 3               # per sensor inside the window
PROVISIONAL = ("delta_h_down_m", "delta_h_up_m", "window_min")

Reading = Tuple[datetime, float]        # (timestamp, stage in metres) -- QC-passed readings only
TIERS = ("Green", "Yellow", "Orange", "Red")


def stage_change(readings: Sequence[Reading], now: datetime, window: timedelta = WINDOW) -> Optional[float]:
    """Change in stage (m) across the window ending at `now`: last minus first reading in the
    window.  None if fewer than MIN_READINGS readings fall inside it."""
    inside = sorted((t, v) for t, v in readings if now - window <= t <= now)
    if len(inside) < MIN_READINGS:
        return None
    return inside[-1][1] - inside[0][1]


def check_blockage(
    upstream: Optional[Sequence[Reading]],
    downstream: Optional[Sequence[Reading]],
    upstream_landslide_tier: Optional[str],
    now: datetime,
    node_tilt_alarm: bool = False,
    delta_down_m: float = DELTA_H_DOWN_M,
    delta_up_m: float = DELTA_H_UP_M,
    window: timedelta = WINDOW,
) -> dict:
    """
    Returns {status, blockage_suspect, trigger_type, evidence, provisional_constants}.
    status: 'off_no_sensors' | 'insufficient_data' | 'clear' | 'blockage_suspect'
    """
    base = dict(provisional_constants=list(PROVISIONAL),
                thresholds=dict(delta_h_down_m=delta_down_m, delta_h_up_m=delta_up_m,
                                window_min=window.total_seconds() / 60))
    if not upstream or not downstream:
        return dict(base, status="off_no_sensors", blockage_suspect=False, trigger_type=None,
                    evidence={"reason": "no paired upstream/downstream stage sensors: check is OFF, not guessed"})

    d_up, d_down = stage_change(upstream, now, window), stage_change(downstream, now, window)
    if d_up is None or d_down is None:
        return dict(base, status="insufficient_data", blockage_suspect=False, trigger_type=None,
                    evidence={"upstream_change_m": d_up, "downstream_change_m": d_down,
                              "reason": f"fewer than {MIN_READINGS} usable readings in the window"})

    slide_trigger = (upstream_landslide_tier in ("Orange", "Red")) or node_tilt_alarm
    stage_pattern = (d_down <= -delta_down_m) and (d_up >= delta_up_m)
    suspect = bool(slide_trigger and stage_pattern)
    evidence = dict(upstream_change_m=round(d_up, 3), downstream_change_m=round(d_down, 3),
                    slide_trigger=slide_trigger, stage_pattern=stage_pattern,
                    upstream_landslide_tier=upstream_landslide_tier, node_tilt_alarm=node_tilt_alarm)
    return dict(base, status="blockage_suspect" if suspect else "clear", blockage_suspect=suspect,
                trigger_type="LANDSLIDE_DAM" if suspect else None, evidence=evidence)


def flag_blocked_segments(road_segment_reach_ids: Iterable[str], blocked_reach_ids: Iterable[str]) -> list[str]:
    """Road segments whose reach id is in the blocked set (excluded before choosing an evacuation route)."""
    blocked = set(blocked_reach_ids)
    return [s for s in road_segment_reach_ids if s in blocked]
