"""
backend/repository.py -- Repository layer over GeoPackage and SQLite.
(Gap Analysis Phase 2)

This module abstracts data access so routers don't need to know whether
static hex data is in a .gpkg file or in SQLite.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import json
import h3

from backend.database import get_db
from backend.onboarding.geopackage import load_region_gpkg, get_region_hex_ids
from backend.onboarding.pipeline import REGION_BY_CODE
from backend.provenance import ProvenanceTag

VILLAGE_CENTROIDS = [
    ("Mundakkai", 11.5185, 76.0524),
    ("Chooralmala", 11.5143, 76.0498),
    ("Attamala", 11.5220, 76.0570),
    ("Punjirimattom", 11.5100, 76.0450),
]

def _nearest_village(lat: float, lon: float) -> str:
    best_dist = float("inf")
    best_name = "Wayanad Sector"
    for name, vlat, vlon in VILLAGE_CENTROIDS:
        d = (lat - vlat)**2 + (lon - vlon)**2
        if d < best_dist:
            best_dist = d
            best_name = name
    return best_name

def get_latest_risk_scores(region_code: str) -> Dict[str, Dict[str, Any]]:
    """Fetch the latest dynamic risk_scores from SQLite for a given region."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT rs.hex_id, rs.risk_score, rs.tier, rs.data_source, rs.confidence_score,
                   rs.lead_time_min, rs.timestamp, rs.sensor_adjusted
            FROM risk_scores rs
            JOIN (
                SELECT hex_id, MAX(timestamp) AS max_ts FROM risk_scores GROUP BY hex_id
            ) latest ON rs.hex_id = latest.hex_id AND rs.timestamp = latest.max_ts
        """).fetchall()

    return {r["hex_id"]: dict(r) for r in rows}

MAX_SCORE_AGE_H = 12.0          # a score older than this is not "current" and is not put on the map

# Older seeded demo hexes (backend/seed*.py) carry an EMPTY region_code.  They are assigned to a region only
# by geography, using the same bounding boxes as scripts/stage0/fetch_landcover.py, so "Wayanad" never
# collects hexes from the other end of India.  Hexes in no box appear in no regional map.
REGION_BBOX = {   # region_code: (south, north, west, east)
    "wayanad-kl": (11.40, 11.70, 75.95, 76.22), "idukki-kl": (9.80, 10.20, 76.80, 77.10),
    "nilgiris-tn": (11.20, 11.55, 76.55, 76.90), "rudraprayag-uk": (30.40, 30.70, 78.85, 79.10),
    "chamoli-uk": (30.30, 30.60, 79.10, 79.40), "kullu-hp": (31.75, 32.10, 77.05, 77.35),
    "mangan-sk": (27.40, 27.70, 88.45, 88.70), "darjeeling-wb": (26.90, 27.20, 88.10, 88.40),
    "ribhoi-ml": (25.70, 26.00, 91.80, 92.10), "dhemaji-as": (27.35, 27.65, 94.30, 94.65),
}


def _in_region_bbox(region_code: str, lat: float, lon: float) -> bool:
    b = REGION_BBOX.get(region_code)
    return bool(b and b[0] <= lat <= b[1] and b[2] <= lon <= b[3])


def _state_from_label(label: str) -> str:
    """'Ribhoi (Nongpoh), Meghalaya (Northeast)' -> 'Meghalaya'."""
    parts = [p.strip() for p in (label or "").split(",")]
    return parts[1].split("(")[0].strip() if len(parts) > 1 else "India"


def get_risk_map_data(region_code: Optional[str] = None, bbox: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Map entries for one region, built ONLY from real stored scores.

    Every value comes from a row in risk_scores (plus the hex's static features).  Hexes that have not been
    scored are simply not returned -- nothing is generated, sampled or defaulted.  (An earlier version
    produced a hash-based "mock distribution" for every region except Wayanad, forced a few hexes to
    Orange/Red, and attached a fake 180-minute lead time and fake sensors; that is gone.)

    Per-hazard tiers come from the physics index (landslide / flood) for hexes scored in this process; after
    a restart they fall back to the overall tier until the next scoring cycle.
    """
    import os
    from datetime import timedelta
    from backend import risk_engine
    from backend.physics_risk import tier_from_score

    min_lon = min_lat = max_lon = max_lat = None
    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
        except Exception:
            min_lon = None
    region_code = region_code or "wayanad-kl"
    reg_meta = REGION_BY_CODE.get(region_code, {"region_code": region_code, "label": region_code.title()})
    label = reg_meta.get("label", region_code)
    state = _state_from_label(label)
    district = label.split(",")[0].split("(")[0].strip()

    max_age = float(os.environ.get("HYDRASENSE_MAX_SCORE_AGE_H", MAX_SCORE_AGE_H))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age)).isoformat()
    # rows of this region, plus legacy hexes with no region code (kept only if they lie in the region's box)
    where, args = "(h.region_code = ? OR h.region_code IS NULL OR h.region_code = '')", [region_code]

    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT rs.hex_id, rs.risk_score, rs.tier, rs.data_source, rs.confidence_score, rs.lead_time_min,
                   rs.timestamp, rs.sensor_adjusted, h.static_features, h.region_code AS hex_region
            FROM risk_scores rs
            JOIN hexes h ON h.hex_id = rs.hex_id
            WHERE {where} AND rs.timestamp >= ?
              AND rs.id = (SELECT MAX(id) FROM risk_scores WHERE hex_id = rs.hex_id)
        """, args + [cutoff]).fetchall()

    entries = []
    for r in rows:
        hid = r["hex_id"]
        try:
            lat, lon = h3.cell_to_latlng(hid)
        except Exception:
            continue
        if not r["hex_region"] and not _in_region_bbox(region_code, lat, lon):
            continue                                                  # legacy hex outside this region's box
        if min_lon is not None and not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        try:
            static = json.loads(r["static_features"] or "{}")
        except (json.JSONDecodeError, TypeError):
            static = {}
        has_cal = bool(static.get("has_local_calibration", False))
        score = float(r["risk_score"])
        tier = r["tier"] or tier_from_score(score)
        mem = risk_engine.LAST_RESULTS.get(hid) or {}
        ff_score, ls_score = mem.get("index_flood"), mem.get("index_landslide")
        entries.append({
            "hex_id": hid,
            "risk_score": score,
            "tier": tier,
            "confidence_score": None if r["confidence_score"] is None else float(r["confidence_score"]),
            "lead_time_min": r["lead_time_min"],
            "data_source": r["data_source"] or "unknown",
            "flood_tier": tier_from_score(ff_score) if ff_score is not None else tier,
            "landslide_tier": tier_from_score(ls_score) if ls_score is not None else tier,
            "has_local_calibration": has_cal,
            "fs_band_widened_for_no_calibration": not has_cal,
            "instrumented_hex": bool(r["sensor_adjusted"]),       # a real/simulated node adjusted this hex
            "sensor_adjusted": bool(r["sensor_adjusted"]),
            "village": _nearest_village(lat, lon) if region_code == "wayanad-kl" else district,
            "lat": lat,
            "lng": lon,
            "region_code": region_code,
            "region_label": label,
            "state": state,
            "district": district,
            "conf_reason": mem.get("confidence_primary_reason"),
        })
    return entries
