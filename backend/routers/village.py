"""
backend/routers/village.py -- village-level risk API (v2 Sec. 14.3).

GET /village/priority?region=...       ranked village table
GET /village/{village_id}/risk?region=...   one village record (Sec. 5.3.5)

Data sources (nothing is invented; a missing input yields a null value plus a stated reason):
  * villages / hexes_static layers from data/regions/{region}.gpkg   (onboarding pipeline output)
  * latest landslide-side hex risk from the risk_scores table
  * flood side: the flood head and per-catchment risk are NOT built yet (backend/ml.py is a stub),
    so `flood` is always null with that reason.

Priority here is RISK-ONLY: exposure and vulnerability (v2 Sec. 11) are not built, so the
table is sorted by alert value and says so in `priority_basis`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, HTTPException, Query

from backend import village_rollup as vr
from backend.database import get_db

router = APIRouter(prefix="/village", tags=["village"])

GPKG_DIR = ROOT / "data" / "regions"
# Upslope sources are searched within this many H3 rings of the footprint.  Res-8 centres are
# ~0.8 km apart, so 12 rings ~ 9.6 km, enough for the ~8 km Wayanad 2024 debris-flow runout.
CANDIDATE_RING_K = 12
PRIORITY_BASIS = "risk_only: exposure and vulnerability are not built (v2 Sec. 11)"
FLOOD_NOTE = ("flood head and per-catchment risk are not built yet "
              "(backend/ml.py heads are stubs); no flood value is reported")


@dataclass
class RegionLayers:
    region_code: str
    villages: list[dict]                 # village_id, name, geometry, population, boundary_quality
    elevation: dict[str, float] = field(default_factory=dict)
    slope_deg: dict[str, float] = field(default_factory=dict)


def load_region_layers(region_code: str) -> RegionLayers:
    """Read villages + hex terrain from the region GeoPackage.  Raises HTTPException if absent."""
    path = GPKG_DIR / f"{region_code}.gpkg"
    if not path.exists():
        raise HTTPException(404, detail=f"region '{region_code}' has no onboarded GeoPackage "
                                        f"({path.name}); run the onboarding pipeline first")
    try:
        import geopandas as gpd
    except ImportError:
        raise HTTPException(503, detail="geopandas is not installed in this environment")
    try:
        vg = gpd.read_file(path, layer="villages")
    except Exception as exc:
        raise HTTPException(404, detail=f"region '{region_code}' has no 'villages' layer: {exc}")
    try:
        hx = gpd.read_file(path, layer="hexes_static")
    except Exception:
        hx = None
    villages = []
    for _, r in vg.iterrows():
        villages.append(dict(
            village_id=str(r.get("village_id")), name=str(r.get("name", "")),
            geometry=r.geometry, population=r.get("population"),
            boundary_quality=str(r.get("boundary_quality", "unknown"))))
    elev, slope = {}, {}
    if hx is not None and "hex_id" in hx.columns:
        for _, r in hx.iterrows():
            if "elevation" in hx.columns and r.get("elevation") == r.get("elevation"):
                elev[r["hex_id"]] = float(r["elevation"])
            if "slope_deg" in hx.columns and r.get("slope_deg") == r.get("slope_deg"):
                slope[r["hex_id"]] = float(r["slope_deg"])
    return RegionLayers(region_code, villages, elev, slope)


MAX_SCORE_AGE_H = 12.0          # scores older than this are not "current" and are ignored (env-overridable)


def latest_hex_risks(hex_ids: set[str]) -> dict[str, dict]:
    """Latest risk_scores row per hex: {hex_id: {risk_score, tier, data_source}}, ignoring rows older
    than MAX_SCORE_AGE_H hours so a stale score is never presented as current."""
    import os
    from datetime import datetime, timedelta, timezone
    if not hex_ids:
        return {}
    max_age = float(os.environ.get("HYDRASENSE_MAX_SCORE_AGE_H", MAX_SCORE_AGE_H))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age)).isoformat()
    out: dict[str, dict] = {}
    with get_db() as conn:
        ids = list(hex_ids)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT r.hex_id, r.risk_score, r.tier, r.data_source FROM risk_scores r "
                f"JOIN (SELECT hex_id, MAX(id) AS mid FROM risk_scores WHERE hex_id IN ({q}) "
                f"GROUP BY hex_id) m ON r.id = m.mid WHERE r.timestamp >= ?", chunk + [cutoff]).fetchall()
            for r in rows:
                out[r["hex_id"]] = dict(risk_score=r["risk_score"], tier=r["tier"],
                                        data_source=r["data_source"])
    return out


def _compute_village(v: dict, layers: RegionLayers) -> dict:
    import h3
    footprint, approx = vr.footprint_hexes(v["geometry"])
    ring = set()
    for h in footprint:
        ring |= set(h3.grid_disk(h, CANDIDATE_RING_K))
    risks = latest_hex_risks(footprint | ring)
    ls = {h: d["risk_score"] for h, d in risks.items() if d["risk_score"] is not None}
    pop = v.get("population")
    per_hex_pop = None
    if pop is not None and pop == pop and len(footprint):
        per_hex_pop = {h: float(pop) / len(footprint) for h in footprint}
    rec = vr.village_record(
        village_id=v["village_id"], footprint=footprint, footprint_approx=approx,
        boundary_quality=v["boundary_quality"], ls_risk=ls, elevation=layers.elevation,
        slope_deg=layers.slope_deg, hex_population=per_hex_pop,
        candidate_hexes=[h for h in ring if h in ls])
    scored = [h for h in footprint if h in ls]
    rec.update(
        name=v["name"], region_code=layers.region_code,
        footprint_hexes_scored=len(scored),
        terrain_available_for_reach=bool(layers.elevation and layers.slope_deg),
        landslide=dict(alert_value=rec["alert_value"], alert_tier=rec["alert_tier"],
                       alert_driver=rec["alert_driver"]),
        flood=None, flood_note=FLOOD_NOTE,
        data_sources=sorted({risks[h]["data_source"] for h in scored if risks[h].get("data_source")}),
    )
    if not scored:
        rec["note"] = "no scored hexes in this village footprint yet"
    return rec


@router.get("/drafts")
def village_drafts():
    """Villages currently holding an alert-draft state, and the last cycle per region.  Drafts are
    NOT published: they still need the two-person authorisation gate."""
    from backend import village_cycle as vc
    return dict(open_drafts=sorted(f"{v}|{h}" for v, h in vc.TRACKER.open_drafts),
                last_cycle=vc.LAST_RUN, note="reporting only; nothing is published",
                reference="HydraSense_v2 Sec. 5.3.4")


SUMMARY_MAX_AGE_S = 1200     # reuse a region summary for 20 min (the scoring cycle is 15 min)


@router.get("/summary")
def village_summary(region: Optional[str] = Query(None, description="one region, or all onboarded regions")):
    """
    Village counts by tier for the KPI cards (v2 Sec. 13.1 'which villages first?').  Uses the counts the
    village cycle already computed when fresh, else computes them.  Unscored villages are counted separately,
    never as Safe.
    """
    from datetime import datetime, timezone
    from backend import village_cycle as vc
    codes = [region] if region else sorted(p.stem for p in GPKG_DIR.glob("*.gpkg"))
    regions, total = [], {"Red": 0, "Orange": 0, "Yellow": 0, "Green": 0}
    villages = scored = 0
    top = None
    for code in codes:
        s = vc.SUMMARY.get(code)
        fresh = s and (datetime.now(timezone.utc) - datetime.fromisoformat(s["at"])).total_seconds() < SUMMARY_MAX_AGE_S
        if not fresh:
            try:
                s = vc.summarise_region(code)
            except HTTPException:
                continue
        regions.append(dict(region_code=code, **s))
        for t, n in s["tier_counts"].items():
            total[t] += n
        villages += s["villages"]
        scored += s["scored"]
        tv = s.get("top_village")
        if tv and (top is None or (tv.get("alert_value") or 0) > (top.get("alert_value") or 0)):
            top = dict(tv, region_code=code)
    return dict(scope=region or "all_onboarded", tier_counts=total, villages=villages, scored_villages=scored,
                unscored_villages=villages - scored, top_village=top, regions=regions,
                basis="landslide village value (v2 Sec. 5.3); flood per village is not built",
                reference="HydraSense_v2 Sec. 13.1")


@router.get("/priority")
def village_priority(region: str = Query(..., description="region_code of an onboarded region"),
                     limit: int = Query(50, ge=1, le=500)):
    layers = load_region_layers(region)
    rows = [_compute_village(v, layers) for v in layers.villages]
    rows.sort(key=lambda r: (r["alert_value"] is not None, r["alert_value"] or 0.0), reverse=True)
    for i, r in enumerate(rows, 1):
        r["priority_rank"] = i if r["alert_value"] is not None else None
    return dict(region=region, priority_basis=PRIORITY_BASIS, count=len(rows),
                villages=rows[:limit], reference="HydraSense_v2 Sec. 5.3, 11.1, 14.3")


@router.get("/{village_id}/risk")
def village_risk(village_id: str, region: str = Query(...)):
    layers = load_region_layers(region)
    for v in layers.villages:
        if v["village_id"] == village_id:
            return dict(**_compute_village(v, layers), priority_basis=PRIORITY_BASIS,
                        reference="HydraSense_v2 Sec. 5.3.5, 14.2")
    raise HTTPException(404, detail=f"village '{village_id}' not found in region '{region}'")
