"""
backend/village_cycle.py -- village-level persistence cycle (v2 Sec. 5.3.4), driven by the scheduler.

Each slow cycle, for every opted-in region (HYDRASENSE_SCORE_REGIONS) that has a GeoPackage:
compute the landslide-side village record, feed its tier to VillagePersistenceTracker, and report
which villages now qualify for an alert DRAFT (Orange/Red held for 2 consecutive cycles, with the
cloudburst / sensor / edge bypass).  This module only reports drafts; it does not publish anything.
Creating the CAP object still goes through the existing two-person authorisation gate.

Cold start (v2 Sec. 5.3.4 / Final 14.6): while the scheduler's cold-start guard is active nothing
is recorded and no draft is returned, so onboarding a region live cannot fire a spurious draft.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.village_rollup import VillagePersistenceTracker

log = logging.getLogger("hydrasense.village_cycle")

TRACKER = VillagePersistenceTracker()
LAST_RUN: dict = {}            # region_code -> {"at": iso, "villages": n, "drafts": [...]}
SUMMARY: dict = {}             # region_code -> {"at", "villages", "scored", "tier_counts", "top_village"}


def summarise_region(region_code: str) -> dict:
    """Village tier counts for one region WITHOUT touching the persistence tracker (for the KPI cards)."""
    from backend.routers import village as vapi
    layers = vapi.load_region_layers(region_code)
    counts = {"Red": 0, "Orange": 0, "Yellow": 0, "Green": 0}
    top = None
    for v in layers.villages:
        rec = vapi._compute_village(v, layers)
        tier = rec.get("alert_tier")
        if tier is None:
            continue
        counts[tier] += 1
        if top is None or (rec.get("alert_value") or 0) > (top.get("alert_value") or 0):
            top = dict(village_id=v["village_id"], name=rec.get("name", ""), alert_tier=tier,
                       alert_value=rec.get("alert_value"))
    SUMMARY[region_code] = {"at": datetime.now(timezone.utc).isoformat(), "villages": len(layers.villages),
                            "scored": sum(counts.values()), "tier_counts": counts, "top_village": top}
    return SUMMARY[region_code]


def run_village_cycle(region_code: str, cold_start: bool = False, tracker: VillagePersistenceTracker | None = None,
                      compute=None, layers=None) -> list[dict]:
    """
    Update the tracker for one region and return the drafts due now:
    [{village_id, name, hazard, draft_tier, reason, alert_value, alert_driver}].
    `compute` / `layers` can be injected for tests; by default the village router's loaders are used.
    """
    if cold_start:
        LAST_RUN[region_code] = {"at": datetime.now(timezone.utc).isoformat(), "villages": 0,
                                 "drafts": [], "note": "cold start: nothing recorded"}
        return []
    tracker = tracker or TRACKER
    if layers is None or compute is None:
        from backend.routers import village as vapi
        layers = layers or vapi.load_region_layers(region_code)
        compute = compute or vapi._compute_village
    drafts = []
    counts = {"Red": 0, "Orange": 0, "Yellow": 0, "Green": 0}
    top = None
    for v in layers.villages:
        rec = compute(v, layers)
        tier = rec.get("alert_tier")
        if tier is None:                                   # unscored village: record nothing
            continue
        counts[tier] = counts.get(tier, 0) + 1
        if top is None or (rec.get("alert_value") or 0) > (top.get("alert_value") or 0):
            top = dict(village_id=v["village_id"], name=rec.get("name", ""), alert_tier=tier,
                       alert_value=rec.get("alert_value"))
        d = tracker.update(v["village_id"], "landslide", tier)
        if d.draft_tier:
            drafts.append(dict(village_id=v["village_id"], name=rec.get("name", ""), hazard="landslide",
                               draft_tier=d.draft_tier, reason=d.reason,
                               alert_value=rec.get("alert_value"), alert_driver=rec.get("alert_driver"),
                               boundary_quality=rec.get("boundary_quality")))
    LAST_RUN[region_code] = {"at": datetime.now(timezone.utc).isoformat(), "villages": len(layers.villages),
                             "drafts": drafts}
    SUMMARY[region_code] = {"at": LAST_RUN[region_code]["at"], "villages": len(layers.villages),
                            "scored": sum(counts.values()), "tier_counts": counts, "top_village": top}
    if drafts:
        log.info("[village_cycle] %s: %d village draft(s) due", region_code, len(drafts))
    return drafts
