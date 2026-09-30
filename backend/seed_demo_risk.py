"""
backend/seed_demo_risk.py
=========================
Seeds realistic VARIED dynamic observations + static terrain features for every
hex in the database, then rescores each hex so the dashboard shows different
tiers (Green / Yellow / Orange / Red) rather than a flat 0.0/Green grid.

Run once after the main seed:
    cd c:\\Users\\mohan\\Music\\project\\HydraSense
    python -m backend.seed_demo_risk
"""
from __future__ import annotations
import json, sys, math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import get_db, init_db
from backend.risk_engine import compute_and_store_risk

TERRAIN_PROFILES = [
    dict(slope=34, HAND=4.0,  soil_c=4.0,  soil_phi=28, soil_depth=1.5, label="Red"),
    dict(slope=8,  HAND=1.2,  soil_c=6.0,  soil_phi=30, soil_depth=2.0, label="Red"),
    dict(slope=26, HAND=9.0,  soil_c=5.0,  soil_phi=27, soil_depth=1.8, label="Orange"),
    dict(slope=18, HAND=6.5,  soil_c=7.0,  soil_phi=32, soil_depth=2.2, label="Orange"),
    dict(slope=14, HAND=14.0, soil_c=8.0,  soil_phi=31, soil_depth=2.5, label="Yellow"),
    dict(slope=6,  HAND=5.0,  soil_c=9.0,  soil_phi=33, soil_depth=3.0, label="Yellow"),
    dict(slope=9,  HAND=22.0, soil_c=10.0, soil_phi=34, soil_depth=3.5, label="Green"),
    dict(slope=4,  HAND=28.0, soil_c=12.0, soil_phi=35, soil_depth=4.0, label="Green"),
]

RAIN_PROFILES = {
    "Red":    dict(rainfall_1h=28.0,  rainfall_3h=62.0,  rainfall_6h=95.0,
                   rainfall_24h=148.0, rainfall_72h_antecedent=230.0,
                   soil_saturation_ratio=0.92, antecedent_precipitation_index=185.0,
                   iot_anomaly_flag=1),
    "Orange": dict(rainfall_1h=14.0,  rainfall_3h=35.0,  rainfall_6h=52.0,
                   rainfall_24h=85.0,  rainfall_72h_antecedent=130.0,
                   soil_saturation_ratio=0.75, antecedent_precipitation_index=110.0,
                   iot_anomaly_flag=0),
    "Yellow": dict(rainfall_1h=6.0,   rainfall_3h=14.0,  rainfall_6h=24.0,
                   rainfall_24h=42.0,  rainfall_72h_antecedent=65.0,
                   soil_saturation_ratio=0.55, antecedent_precipitation_index=60.0,
                   iot_anomaly_flag=0),
    "Green":  dict(rainfall_1h=0.5,   rainfall_3h=1.2,   rainfall_6h=2.5,
                   rainfall_24h=5.0,   rainfall_72h_antecedent=12.0,
                   soil_saturation_ratio=0.25, antecedent_precipitation_index=15.0,
                   iot_anomaly_flag=0),
}


def get_all_hex_ids(conn):
    rows = conn.execute("SELECT hex_id FROM hexes ORDER BY hex_id").fetchall()
    return [r[0] for r in rows]


def seed_static_features(conn, hex_id, profile):
    feats = {
        "slope":      profile["slope"],
        "slope_deg":  profile["slope"],
        "HAND_m":     profile["HAND"],
        "hand_m":     profile["HAND"],
        "soil_cohesion_kpa":       profile["soil_c"],
        "soil_friction_angle_deg": profile["soil_phi"],
        "soil_depth_m":            profile["soil_depth"],
        "ndvi_mean":  0.48,
        "TWI": math.log(1.0 / max(math.tan(math.radians(profile["slope"])), 0.01)),
        "elevation":  850.0 + profile["slope"] * 12,
        "drainage_density": 2.1,
        "gsi_susceptibility_class": 3 if profile["slope"] > 20 else 2,
        "historical_event_count_500m": 3 if profile["label"] in ("Red", "Orange") else 0,
    }
    conn.execute(
        "UPDATE hexes SET static_features = ? WHERE hex_id = ?",
        (json.dumps(feats), hex_id)
    )


def seed_observation(conn, hex_id, profile, rain):
    ts = datetime.now(timezone.utc).isoformat()
    dynamic = dict(rain)
    dynamic["rain_intensity_mm_hr"] = rain["rainfall_1h"]
    conn.execute(
        "INSERT INTO observations (hex_id, timestamp, provenance, dynamic_features) VALUES (?, ?, 'SIMULATED', ?)",
        (hex_id, ts, json.dumps(dynamic))
    )


def run():
    print("[seed_demo_risk] Starting ...")
    init_db()
    with get_db() as conn:
        hex_ids = get_all_hex_ids(conn)
        if not hex_ids:
            print("[seed_demo_risk] ERROR: no hexes in DB. Run seed.py first.")
            return
        print(f"[seed_demo_risk] Found {len(hex_ids)} hexes. Injecting varied data ...")
        for i, hex_id in enumerate(hex_ids):
            profile = TERRAIN_PROFILES[i % len(TERRAIN_PROFILES)]
            rain = RAIN_PROFILES[profile["label"]]
            seed_static_features(conn, hex_id, profile)
            seed_observation(conn, hex_id, profile, rain)
            print(f"  {hex_id[:18]}... -> target {profile['label']}")

    print("[seed_demo_risk] Rescoring all hexes ...")
    with get_db() as conn:
        hex_ids = get_all_hex_ids(conn)

    errors = 0
    for hex_id in hex_ids:
        try:
            result = compute_and_store_risk(hex_id)
            tier  = result.get("tier", "?") if result else "FAILED"
            score = result.get("risk_score", 0) if result else 0
            print(f"  {hex_id[:18]}... -> {tier:6s}  score={score:.1f}")
        except Exception as e:
            print(f"  {hex_id[:18]}... -> ERROR: {e}")
            errors += 1

    print(f"[seed_demo_risk] Done. {len(hex_ids)} hexes rescored, {errors} errors.")


if __name__ == "__main__":
    run()
