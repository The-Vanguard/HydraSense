"""
tests/test_village_rollup.py -- v2 Sec. 5.3 village roll-up (pure logic, no DB / network).

Synthetic terrain: a disk of H3 res-8 cells whose elevation falls to the east at a chosen slope
angle, so steepest descent runs west -> east and the reach-angle rule can be checked by hand.
"""
import math
import sys
from pathlib import Path

import h3
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import village_rollup as vr  # noqa: E402

ORIGIN = h3.latlng_to_cell(11.5, 76.15, 8)


def make_terrain(slope_deg, k=7):
    """cells, elevation, x_m (east distance) for a disk; elevation drops east at slope_deg."""
    lat0, lon0 = h3.cell_to_latlng(ORIGIN)
    cells = list(h3.grid_disk(ORIGIN, k))
    elev, x = {}, {}
    for c in cells:
        la, lo = h3.cell_to_latlng(c)
        xm = (lo - lon0) * 111_320 * math.cos(math.radians(la))
        x[c] = xm
        elev[c] = 1500.0 - xm * math.tan(math.radians(slope_deg))
    return cells, elev, x


def setup(slope_deg, source_risk=80.0, foot_risk=20.0):
    cells, elev, x = make_terrain(slope_deg)
    west = sorted(cells, key=lambda c: x[c])[:3]
    footprint = {c for c in cells if x[c] > 3000 and abs(x[c]) < 4500}
    ls = {c: foot_risk for c in cells}
    sl = {c: slope_deg for c in cells}
    src = west[0]
    ls[src] = source_risk
    return cells, elev, footprint, ls, sl, src


# ---------------------------------------------------------------- tiers
@pytest.mark.parametrize("score,tier", [(0, "Green"), (29.9, "Green"), (30, "Yellow"), (54.9, "Yellow"),
                                        (55, "Orange"), (74.9, "Orange"), (75, "Red"), (100, "Red")])
def test_tier_boundaries(score, tier):
    assert vr.tier_from_score(score) == tier


# ---------------------------------------------------------------- footprint value
def test_small_footprint_uses_max():
    v, n = vr.footprint_value([10, 90, 20])
    assert (v, n) == (90, 3)


def test_large_footprint_uses_p90_not_max():
    v, n = vr.footprint_value([40] * 9 + [90])
    assert n == 10 and 40 <= v < 90            # one noisy hex must not set the village value


def test_footprint_value_ignores_nan_and_empty():
    assert vr.footprint_value([]) == (None, 0)
    assert vr.footprint_value([float("nan"), 50]) == (50, 1)


# ---------------------------------------------------------------- reach rule
def test_steep_slope_source_reaches_footprint():
    cells, elev, footprint, ls, sl, src = setup(22)
    out = vr.landslide_village_value(footprint, ls, elev, sl)
    assert out["alert_driver"] == "upslope_source"
    assert out["alert_value"] == 80.0 and out["source_hex"] == src
    assert out["footprint_p90"] == 20.0


def test_gentle_slope_source_does_not_reach():
    # 10 deg terrain: source is a candidate only if slope >= 15 deg, so pass 20 deg as its slope
    # but let the actual terrain be gentle -> the reach-angle stop rule must end the trace.
    cells, elev, footprint, ls, sl, src = setup(10)
    sl = {c: 20.0 for c in cells}
    out = vr.landslide_village_value(footprint, ls, elev, sl)
    assert out["alert_driver"] == "footprint" and out["alert_value"] == 20.0
    assert out["source_reach_max"] is None


def test_low_slope_or_low_risk_sources_are_not_candidates():
    cells, elev, footprint, ls, sl, src = setup(22)
    sl_low = dict(sl)
    sl_low[src] = 10.0                                      # below 15 deg
    assert vr.landslide_village_value(footprint, ls, elev, sl_low)["alert_driver"] == "footprint"
    ls_low = dict(ls)
    ls_low[src] = 25.0                                      # below Yellow
    assert vr.landslide_village_value(footprint, ls_low, elev, sl)["alert_driver"] == "footprint"


def test_source_inside_footprint_is_not_double_counted():
    cells, elev, footprint, ls, sl, src = setup(22, source_risk=20.0)
    inside = next(iter(footprint))
    ls[inside] = 95.0
    out = vr.landslide_village_value(footprint, ls, elev, sl)
    assert out["alert_driver"] == "footprint" and out["source_reach_max"] is None


def test_missing_elevation_does_not_crash_or_reach():
    cells, elev, footprint, ls, sl, src = setup(22)
    assert vr.trace_reaches_footprint(src, footprint, {}) is False
    assert vr.trace_reaches_footprint(src, footprint, {src: float("nan")}) is False


# ---------------------------------------------------------------- flood
def test_flood_kept_inside_extent_reduced_outside():
    kept = vr.flood_village_value({"c1": 82.0, "c2": 40.0}, footprint_in_screen_extent=True)
    assert kept["alert_value"] == 82.0 and kept["catchment_id"] == "c1" and not kept["tier_reduced"]
    red = vr.flood_village_value({"c1": 82.0}, footprint_in_screen_extent=False)
    assert vr.tier_from_score(red["alert_value"]) == "Orange" and red["tier_reduced"]
    assert red["alert_driver"] == "catchment"


def test_flood_with_no_catchment_is_none():
    assert vr.flood_village_value({}, True)["alert_value"] is None


# ---------------------------------------------------------------- persistence
def test_orange_needs_two_consecutive_cycles():
    t = vr.VillagePersistenceTracker()
    assert t.update("v", "ls", "Orange").draft_tier is None
    d = t.update("v", "ls", "Orange")
    assert d.draft_tier == "Orange" and d.consecutive == 2


def test_single_spike_resets():
    t = vr.VillagePersistenceTracker()
    t.update("v", "ls", "Orange")
    assert t.update("v", "ls", "Yellow").draft_tier is None
    assert t.update("v", "ls", "Orange").draft_tier is None       # streak restarted


def test_cloudburst_and_sensor_and_edge_bypass():
    for kw in ({"trigger_type": "CLOUDBURST_FLASH"}, {"sensor_confirmed": True}, {"edge_alarm": True}):
        t = vr.VillagePersistenceTracker()
        d = t.update("v", "ff", "Red", **kw)
        assert d.draft_tier == "Red" and d.reason.startswith("bypass")


def test_escalation_after_draft_is_immediate():
    t = vr.VillagePersistenceTracker()
    t.update("v", "ls", "Orange"); t.update("v", "ls", "Orange")
    assert t.update("v", "ls", "Red").draft_tier == "Red"


def test_red_after_orange_drafts_orange_first():
    t = vr.VillagePersistenceTracker()
    t.update("v", "ls", "Orange")
    d = t.update("v", "ls", "Red")
    assert d.draft_tier == "Orange"


def test_hazards_and_villages_are_independent():
    t = vr.VillagePersistenceTracker()
    t.update("v1", "ls", "Orange")
    assert t.update("v1", "ff", "Orange").draft_tier is None
    assert t.update("v2", "ls", "Orange").draft_tier is None


def test_close_resets_state():
    t = vr.VillagePersistenceTracker()
    t.update("v", "ls", "Orange"); t.update("v", "ls", "Orange")
    t.close("v", "ls")
    assert t.update("v", "ls", "Orange").draft_tier is None


# ---------------------------------------------------------------- footprint_hexes + record
def test_footprint_hexes_polygon_and_tiny_fallback():
    shapely_geom = pytest.importorskip("shapely.geometry")
    poly = shapely_geom.box(76.10, 11.45, 76.20, 11.55)               # ~ 11 km square
    cells, approx = vr.footprint_hexes(poly)
    assert len(cells) > 5 and approx is False
    tiny = shapely_geom.box(76.1500, 11.5000, 76.1503, 11.5003)        # ~ 30 m
    cells, approx = vr.footprint_hexes(tiny)
    assert len(cells) == 1 and approx is True                           # flagged, not silent


def test_village_record_fields_and_exposure_context():
    cells, elev, footprint, ls, sl, src = setup(22)
    pop = {h: 100.0 for h in footprint}
    rec = vr.village_record("V1", footprint, False, "osm", ls, elev, sl, hex_population=pop)
    for key in ("village_id", "exposure_weighted_mean", "footprint_p90", "source_reach_max",
                "alert_value", "alert_driver", "footprint_hex_count", "boundary_quality",
                "footprint_approx"):
        assert key in rec
    assert rec["alert_tier"] == "Red" and rec["alert_driver"] == "upslope_source"
    assert rec["exposure_weighted_mean"] == pytest.approx(20.0)        # context only
    assert rec["boundary_quality"] == "osm"
