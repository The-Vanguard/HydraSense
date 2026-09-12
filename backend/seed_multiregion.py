"""
backend/seed_multiregion.py -- Phase 13: seeds the live DB with real hexes +
real historical events for the 9 non-Wayanad multiregion locations (Idukki,
Rudraprayag, Chamoli, Ribhoi, Nilgiris, Sikkim/Mangan, Darjeeling/Kalimpong,
Kullu, Dhemaji). Wayanad's 4 villages stay seeded by seed.py, untouched.

Kept separate from seed.py (Phase 4, Wayanad-owned) per CLAUDE.md's
don't-touch-other-phases rule -- this is new Phase-13 territory.

Sources (all real, already built earlier this session):
  data/multiregion/events/terrain_features_points.json  -- real SRTM30m+pysheds terrain
  data/multiregion/events/flood_events_labeled_step2.csv -- real India Flood Inventory v3 events

HARD CONSTRAINT (CLAUDE.md, this session's own decision): the live XGBoost
model (ml/models/fusion_model.pkl) was trained on a different, frozen SRS §9
feature schema than this dataset has (no land_use_class/ndvi_mean/
gsi_susceptibility_class/factor_of_safety/simulated_ffgs_signal/
simulated_gsi_signal here -- CLAUDE.md forbids fetching those). Feeding these
hexes through it would mean fabricating those fields. So: NO risk_scores rows
are written here. These hexes only carry real historical_events -- a sourced,
non-live context layer, not a live risk prediction.

Dhemaji is scoped to its 112 locally-listed rows (<=10 districts), same
DHEMAJI_MAX_DISTRICTS cut used in data/multiregion/scripts/build_event_centered_samples.py.
`type` stored here is the ACTUAL recorded flood_cause_final (ambiguous /
riverine_flood / flash_flood / landslide_only / unknown) -- NOT the
ML-pipeline's per-region flash_flood default, since that default was a
sample-labeling judgment call for model training, not a factual claim about
what a historical record actually was.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import h3

from backend.database import get_db

TERRAIN_JSON = ROOT / "data" / "multiregion" / "events" / "terrain_features_points.json"
EVENTS_CSV = ROOT / "data" / "multiregion" / "events" / "flood_events_labeled_step2.csv"

# terrain_features_points.json key -> (target_location in EVENTS_CSV, default/HQ point name)
# default point matches the same regional defaults already established in
# data/multiregion/scripts/build_event_centered_samples.py's REGION_POINTS.
REGIONS = {
    "Idukki":       ("Idukki",               "Idukki_district_centroid_proxy_Painavu"),
    "Rudraprayag":  ("Rudraprayag",           "Rudraprayag_town"),
    "Chamoli":      ("Chamoli",               "Gopeshwar"),
    "Ribhoi":       ("Ribhoi",                "Nongpoh_town_district_HQ"),
    "Nilgiris":     ("Nilgiris",              "Ooty_Udhagamandalam_district_HQ"),
    "Sikkim":       ("Sikkim/Mangan",         "Mangan_district_HQ"),
    "Darjeeling":   ("Darjeeling/Kalimpong",  "Darjeeling_town_district_HQ"),
    "Kullu":        ("Kullu",                 "Kullu_town_district_HQ"),
    "Dhemaji":      ("Dhemaji",               "Dhemaji_town_district_HQ"),
}

DHEMAJI_MAX_DISTRICTS = 10
H3_RES = 8  # matches seed.py's Wayanad resolution


def load_terrain() -> dict:
    return json.loads(TERRAIN_JSON.read_text())


def seed_multiregion_hexes(conn, terrain: dict) -> dict[str, str]:
    """Insert one hex per real terrain point. Returns {(region_key, point_name): hex_id}."""
    point_to_hex: dict[str, str] = {}
    n_hexes = 0
    for region_key in REGIONS:
        points = terrain.get(region_key, {})
        for point_name, feats in points.items():
            lat, lon = feats.get("lat"), feats.get("lon")
            if lat is None or lon is None:
                continue
            hid = h3.latlng_to_cell(lat, lon, H3_RES)
            boundary = h3.cell_to_boundary(hid)
            geom = json.dumps({
                "type": "Polygon",
                "coordinates": [[[lon_, lat_] for lat_, lon_ in boundary]]
            })
            static_features = {k: v for k, v in feats.items() if k not in ("lat", "lon")}
            conn.execute(
                "INSERT OR IGNORE INTO hexes (hex_id, geom, static_features) VALUES (?,?,?)",
                (hid, geom, json.dumps(static_features))
            )
            point_to_hex[f"{region_key}::{point_name}"] = hid
            n_hexes += 1
    print(f"[seed_multiregion] hexes: {n_hexes} real multiregion points seeded (no risk_scores -- see module docstring)")
    return point_to_hex


def seed_multiregion_events(conn, point_to_hex: dict[str, str]) -> None:
    df = pd.read_csv(EVENTS_CSV, low_memory=False)
    total = 0
    for region_key, (target_location, default_point) in REGIONS.items():
        sub = df[df["target_location"] == target_location].copy()
        if region_key == "Dhemaji":
            n_districts = sub["Districts"].astype(str).apply(lambda s: len(s.split(",")))
            sub = sub[n_districts <= DHEMAJI_MAX_DISTRICTS]

        default_hex = point_to_hex.get(f"{region_key}::{default_point}")
        if default_hex is None:
            print(f"[seed_multiregion] WARNING: no hex for {region_key} default point {default_point!r} -- skipping region")
            continue

        def _s(val, default=""):
            return default if pd.isna(val) else str(val)

        # Real events can affect multiple districts and legitimately share
        # one UEI across regions (same flood, multiple affected districts in
        # the source data) -- event_id is a global PK here, so a bare UEI
        # would let a later region's INSERT OR REPLACE silently overwrite an
        # earlier region's row for the same real event. Region-qualify the
        # stored key so both real per-district records survive; the raw UEI
        # stays fully visible as the prefix.
        n = 0
        for _, row in sub.iterrows():
            uei = _s(row.get("UEI"), f"{region_key}-{n+1:04d}")
            conn.execute(
                """INSERT OR REPLACE INTO historical_events
                   (event_id, hex_id, date, type, severity, source, coordinate_precision, region)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    f"{uei}::{region_key}",
                    default_hex,
                    _s(row.get("Start Date")),
                    _s(row.get("flood_cause_final"), "unknown"),
                    _s(row.get("Severity")),
                    _s(row.get("data_source"), _s(row.get("Event Source"))),
                    _s(row.get("coordinate_precision"), "district-level"),
                    target_location,
                )
            )
            n += 1
        print(f"[seed_multiregion] {target_location}: {n} real historical events seeded")
        total += n
    print(f"[seed_multiregion] historical_events: {total} total real multiregion events seeded")


def run_seed_multiregion() -> None:
    print("[seed_multiregion] Seeding real multiregion hexes + historical events...")
    terrain = load_terrain()
    with get_db() as conn:
        point_to_hex = seed_multiregion_hexes(conn, terrain)
        seed_multiregion_events(conn, point_to_hex)
    print("[seed_multiregion] Done.")


if __name__ == "__main__":
    from backend.database import init_db
    init_db()
    run_seed_multiregion()
