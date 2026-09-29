"""
backend/village_rollup.py -- village-level roll-up of hex / catchment risk.

Implements v2 Sec. 5.3 (village mapping and alert values), 5.3.4 (persistence with bypasses)
and 5.3.5 (village record).  Pure functions plus a small in-memory tracker: no database, no
network, so it can be unit-tested (tests/test_village_rollup.py) and wired to the API later.

Design notes (all values are v2's provisional defaults, NOT fitted results):
  * Village level is a REPORTING resolution.  Only terrain and local sensors are village-scale;
    rainfall is a ~1 km terrain-adjusted field (v2 Sec. 6.3).  Nothing here claims otherwise.
  * Landslide value = max(P90 of footprint hex risk, max risk of upslope sources whose runout
    reaches the footprint).  P90 (not max) because a max over several noisy hexes biases large
    villages upward; with <= 3 footprint hexes the max is used (v2 Sec. 5.3.2).
  * The reach rule is a screening approximation (reach angle alpha, initial 15 deg), not a
    runout model.  It walks steepest-descent over the hex graph using hex elevations.
  * Flood value is catchment-anchored (v2 Sec. 5.3.3); reduced one tier when the footprint is
    outside the screening extent.  The HAND extent is coarse: no per-building statement.
  * Persistence (Sec. 5.3.4): Orange/Red needs 2 consecutive cycles at that tier before a
    draft; bypass for CLOUDBURST_FLASH, any sensor-confirmed trigger, or an edge-node alarm.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Tiers (same names and cut points as ml/models/train_fusion_model.py, SRS 10.4;
# cut points are project defaults pending calibration, v2 Sec. 9.1)
# ---------------------------------------------------------------------------
TIERS = ("Green", "Yellow", "Orange", "Red")
TIER_MIN_SCORE = {"Green": 0.0, "Yellow": 30.0, "Orange": 55.0, "Red": 75.0}
TIER_MAX_SCORE = {"Green": 29.999, "Yellow": 54.999, "Orange": 74.999, "Red": 100.0}
YELLOW_MIN = TIER_MIN_SCORE["Yellow"]

# Provisional parameters (v2 Sec. 5.3.2 / 5.3.4)
SMALL_FOOTPRINT_HEXES = 3          # <= this many hexes: use max instead of P90
SOURCE_MIN_SLOPE_DEG = 15.0
REACH_ALPHA_DEG = 15.0
REACH_MAX_STEPS = 60
PERSISTENCE_CYCLES = 2
BYPASS_TRIGGERS = frozenset({"CLOUDBURST_FLASH"})


def tier_rank(tier: str) -> int:
    return TIERS.index(tier)


def tier_from_score(score: float) -> str:
    for tier in reversed(TIERS):
        if score >= TIER_MIN_SCORE[tier]:
            return tier
    return "Green"


def _reduce_one_tier(score: float) -> tuple[float, str]:
    """One tier lower; the score is capped at the top of that lower tier."""
    lower = TIERS[max(tier_rank(tier_from_score(score)) - 1, 0)]
    return min(score, TIER_MAX_SCORE[lower]), lower


# ---------------------------------------------------------------------------
# Footprint hexes
# ---------------------------------------------------------------------------
def footprint_hexes(geom, res: int = 8) -> tuple[set[str], bool]:
    """
    H3 cells covering a village polygon.  Returns (cells, footprint_approx).
    If the polygon is smaller than a cell (no cell centre falls inside), fall back to the cell
    containing the centroid and flag footprint_approx = True -- never silently.
    """
    import h3
    try:
        cells = set(h3.geo_to_cells(geom, res))
    except Exception:
        cells = set()
    if cells:
        return cells, False
    c = geom.centroid
    return {h3.latlng_to_cell(c.y, c.x, res)}, True


# ---------------------------------------------------------------------------
# Landslide village value (Sec. 5.3.2)
# ---------------------------------------------------------------------------
def footprint_value(scores: Iterable[float]) -> tuple[Optional[float], int]:
    """LS_foot: 90th percentile of footprint hex risk (max when <= 3 hexes). Returns (value, n)."""
    s = [float(x) for x in scores if x is not None and not np.isnan(x)]
    if not s:
        return None, 0
    if len(s) <= SMALL_FOOTPRINT_HEXES:
        return max(s), len(s)
    return float(np.percentile(s, 90)), len(s)


def _hex_dist_m(a: str, b: str) -> float:
    import h3
    (la, lo), (lb, lc) = h3.cell_to_latlng(a), h3.cell_to_latlng(b)
    p = math.radians
    x = math.sin(p(lb - la) / 2) ** 2 + math.cos(p(la)) * math.cos(p(lb)) * math.sin(p(lc - lo) / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(x))


def trace_reaches_footprint(
    source: str,
    footprint: set[str],
    elevation: Mapping[str, float],
    alpha_deg: float = REACH_ALPHA_DEG,
    max_steps: int = REACH_MAX_STEPS,
) -> bool:
    """
    Reach-angle rule.  From `source`, repeatedly step to the lowest neighbouring cell that is
    lower than the current one (steepest descent on the hex graph).  Stop when the angle from
    the source to the current cell, atan((z_source - z_now) / horizontal_distance), falls below
    alpha, when there is no lower neighbour (pit / missing elevation), or after max_steps.
    Returns True if any visited cell is in the footprint.  Screening approximation only.
    """
    import h3
    z_src = elevation.get(source)
    if z_src is None or np.isnan(z_src):
        return False
    cur = source
    tan_alpha = math.tan(math.radians(alpha_deg))
    for _ in range(max_steps):
        z_cur = elevation.get(cur)
        nbrs = [n for n in h3.grid_ring(cur, 1)
                if elevation.get(n) is not None and not np.isnan(elevation[n]) and elevation[n] < z_cur]
        if not nbrs:
            return False
        cur = min(nbrs, key=lambda n: elevation[n])
        dist = _hex_dist_m(source, cur)
        if dist <= 0 or (z_src - elevation[cur]) / dist < tan_alpha:
            return False
        if cur in footprint:
            return True
    return False


def landslide_village_value(
    footprint: set[str],
    ls_risk: Mapping[str, float],
    elevation: Mapping[str, float],
    slope_deg: Mapping[str, float],
    candidate_hexes: Optional[Iterable[str]] = None,
    alpha_deg: float = REACH_ALPHA_DEG,
) -> dict:
    """
    LS_village = max(LS_foot, max over reaching sources of risk_source).
    Candidate sources: hexes outside the footprint with slope >= 15 deg and risk >= Yellow.
    `candidate_hexes` limits the search (e.g. hexes upslope within some radius); default is
    every hex in ls_risk.
    """
    foot_val, n = footprint_value(ls_risk.get(h) for h in footprint)
    pool = candidate_hexes if candidate_hexes is not None else ls_risk.keys()
    best_src, best_val = None, None
    for h in pool:
        if h in footprint:
            continue
        r, sl = ls_risk.get(h), slope_deg.get(h)
        if r is None or sl is None or np.isnan(r) or np.isnan(sl):
            continue
        if sl < SOURCE_MIN_SLOPE_DEG or r < YELLOW_MIN:
            continue
        if best_val is not None and r <= best_val:
            continue                       # cannot improve the maximum; skip the trace
        if trace_reaches_footprint(h, footprint, elevation, alpha_deg):
            best_src, best_val = h, r
    if foot_val is None and best_val is None:
        return dict(alert_value=None, alert_driver=None, footprint_p90=None, source_reach_max=None,
                    source_hex=None, footprint_hex_count=n)
    if best_val is not None and (foot_val is None or best_val > foot_val):
        value, driver = best_val, "upslope_source"
    else:
        value, driver = foot_val, "footprint"
    return dict(alert_value=value, alert_driver=driver, footprint_p90=foot_val,
                source_reach_max=best_val, source_hex=best_src, footprint_hex_count=n)


# ---------------------------------------------------------------------------
# Flood village value (Sec. 5.3.3)
# ---------------------------------------------------------------------------
def flood_village_value(
    linked_catchment_risk: Mapping[str, float],
    footprint_in_screen_extent: bool,
) -> dict:
    """
    The village takes the flood value of the linked micro-catchment with the highest risk.
    If the footprint intersects the screening inundation extent or the low-HAND stream buffer,
    the value is kept; otherwise it is reduced by one tier.  The extent is a coarse screen:
    callers must not present it as a per-building flood zone.
    """
    vals = {k: float(v) for k, v in linked_catchment_risk.items() if v is not None and not np.isnan(v)}
    if not vals:
        return dict(alert_value=None, alert_driver=None, catchment_id=None, tier_reduced=False)
    cid = max(vals, key=vals.get)
    v = vals[cid]
    reduced = False
    if not footprint_in_screen_extent:
        v, _ = _reduce_one_tier(v)
        reduced = tier_from_score(vals[cid]) != "Green"
    return dict(alert_value=v, alert_driver="catchment", catchment_id=cid, tier_reduced=reduced)


# ---------------------------------------------------------------------------
# Persistence with bypasses (Sec. 5.3.4)
# ---------------------------------------------------------------------------
@dataclass
class PersistenceDecision:
    draft_tier: Optional[str]      # tier of the alert draft to create now, or None
    reason: str                    # human-readable, logged with the draft
    consecutive: int               # consecutive cycles at >= current alert tier


@dataclass
class VillagePersistenceTracker:
    """
    Keeps the last `PERSISTENCE_CYCLES` tiers per (village_id, hazard).  In-memory; the caller
    persists it (like persistent_threat.py) if the process must survive restarts.
    """
    history: dict = field(default_factory=dict)
    open_drafts: set = field(default_factory=set)

    def update(
        self,
        village_id: str,
        hazard: str,
        tier: str,
        trigger_type: Optional[str] = None,
        sensor_confirmed: bool = False,
        edge_alarm: bool = False,
    ) -> PersistenceDecision:
        key = (village_id, hazard)
        h = self.history.setdefault(key, [])
        h.append(tier)
        del h[:-PERSISTENCE_CYCLES]
        rank = tier_rank(tier)
        if rank < tier_rank("Orange"):
            return PersistenceDecision(None, "below Orange", 0)
        # consecutive cycles (up to the window) at >= the current tier
        consecutive = 0
        for t in reversed(h):
            if tier_rank(t) >= rank:
                consecutive += 1
            else:
                break
        if key in self.open_drafts:
            # Once a draft exists, escalation / de-escalation follows Sec. 9.6 unchanged.
            return PersistenceDecision(tier, "open draft: no persistence wait", consecutive)
        if trigger_type in BYPASS_TRIGGERS:
            self.open_drafts.add(key)
            return PersistenceDecision(tier, f"bypass: {trigger_type}", consecutive)
        if sensor_confirmed or edge_alarm:
            self.open_drafts.add(key)
            return PersistenceDecision(tier, "bypass: sensor/edge-confirmed", consecutive)
        if consecutive >= PERSISTENCE_CYCLES:
            self.open_drafts.add(key)
            return PersistenceDecision(tier, f"{consecutive} consecutive cycles", consecutive)
        # Not enough history at this tier: a one-off Red after an Orange still counts for Orange
        if rank == tier_rank("Red") and len(h) >= PERSISTENCE_CYCLES \
                and all(tier_rank(t) >= tier_rank("Orange") for t in h):
            self.open_drafts.add(key)
            return PersistenceDecision("Orange", "Orange held 2 cycles; Red not yet persistent", consecutive)
        return PersistenceDecision(None, f"waiting: {consecutive}/{PERSISTENCE_CYCLES} cycles", consecutive)

    def close(self, village_id: str, hazard: str) -> None:
        self.open_drafts.discard((village_id, hazard))
        self.history.pop((village_id, hazard), None)


# ---------------------------------------------------------------------------
# Village record (Sec. 5.3.5)
# ---------------------------------------------------------------------------
def village_record(
    village_id: str,
    footprint: set[str],
    footprint_approx: bool,
    boundary_quality: str,
    ls_risk: Mapping[str, float],
    elevation: Mapping[str, float],
    slope_deg: Mapping[str, float],
    hex_population: Optional[Mapping[str, float]] = None,
    candidate_hexes: Optional[Iterable[str]] = None,
) -> dict:
    """Landslide-side village record.  `exposure_weighted_mean` is context only (never alerted on)."""
    ls = landslide_village_value(footprint, ls_risk, elevation, slope_deg, candidate_hexes)
    ewm = None
    if hex_population:
        w = [(ls_risk.get(h), hex_population.get(h, 0.0)) for h in footprint]
        w = [(r, p) for r, p in w if r is not None and not np.isnan(r) and p > 0]
        if w:
            ewm = float(sum(r * p for r, p in w) / sum(p for _, p in w))
    return dict(
        village_id=village_id,
        exposure_weighted_mean=ewm,
        footprint_p90=ls["footprint_p90"],
        source_reach_max=ls["source_reach_max"],
        source_hex=ls["source_hex"],
        alert_value=ls["alert_value"],
        alert_driver=ls["alert_driver"],
        alert_tier=None if ls["alert_value"] is None else tier_from_score(ls["alert_value"]),
        footprint_hex_count=ls["footprint_hex_count"],
        boundary_quality=boundary_quality,
        footprint_approx=footprint_approx,
    )
