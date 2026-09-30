"""
Targeted demo seeder: only Wayanad bbox hexes (11.4-11.7N, 75.95-76.22E).
Uses cached Open-Meteo data to avoid hanging on live API calls.
Run: python backend/seed_wayanad.py
"""
import sys, json, math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import get_db

TERRAIN = [
    dict(slope=34, HAND=4.0,  soil_c=4.0,  soil_phi=28, soil_depth=1.5, label="Red"),
    dict(slope=8,  HAND=1.2,  soil_c=6.0,  soil_phi=30, soil_depth=2.0, label="Red"),
    dict(slope=26, HAND=9.0,  soil_c=5.0,  soil_phi=27, soil_depth=1.8, label="Orange"),
    dict(slope=18, HAND=6.5,  soil_c=7.0,  soil_phi=32, soil_depth=2.2, label="Orange"),
    dict(slope=14, HAND=14.0, soil_c=8.0,  soil_phi=31, soil_depth=2.5, label="Yellow"),
    dict(slope=6,  HAND=5.0,  soil_c=9.0,  soil_phi=33, soil_depth=3.0, label="Yellow"),
    dict(slope=9,  HAND=22.0, soil_c=10.0, soil_phi=34, soil_depth=3.5, label="Green"),
    dict(slope=4,  HAND=28.0, soil_c=12.0, soil_phi=35, soil_depth=4.0, label="Green"),
]

RAIN = {
    "Red":    dict(rainfall_1h=28.0, rainfall_3h=62.0, rainfall_6h=95.0,
                   rainfall_24h=148.0, rainfall_72h_antecedent=230.0,
                   soil_saturation_ratio=0.92, antecedent_precipitation_index=185.0,
                   iot_anomaly_flag=1),
    "Orange": dict(rainfall_1h=14.0, rainfall_3h=35.0, rainfall_6h=52.0,
                   rainfall_24h=85.0, rainfall_72h_antecedent=130.0,
                   soil_saturation_ratio=0.75, antecedent_precipitation_index=110.0,
                   iot_anomaly_flag=0),
    "Yellow": dict(rainfall_1h=6.0,  rainfall_3h=14.0, rainfall_6h=24.0,
                   rainfall_24h=42.0, rainfall_72h_antecedent=65.0,
                   soil_saturation_ratio=0.55, antecedent_precipitation_index=60.0,
                   iot_anomaly_flag=0),
    "Green":  dict(rainfall_1h=0.5,  rainfall_3h=1.2,  rainfall_6h=2.5,
                   rainfall_24h=5.0,  rainfall_72h_antecedent=12.0,
                   soil_saturation_ratio=0.25, antecedent_precipitation_index=15.0,
                   iot_anomaly_flag=0),
}

TIER_SCORES = {"Red": 96.0, "Orange": 68.0, "Yellow": 42.0, "Green": 8.0}
TIER_CONF   = {"Red": 72.0, "Orange": 65.0, "Yellow": 58.0, "Green": 45.0}
TIER_FS     = {"Red": 0.85, "Orange": 1.15, "Yellow": 1.45, "Green": 2.10}
TIER_LEAD   = {"Red": 45,   "Orange": 120,  "Yellow": None,  "Green": None}

def run():
    import h3

    with get_db() as conn:
        rows = conn.execute("SELECT hex_id FROM hexes ORDER BY hex_id").fetchall()
        hex_ids = [r[0] for r in rows]

    # Filter to Wayanad bbox
    wayanad = []
    for hid in hex_ids:
        try:
            lat, lon = h3.cell_to_latlng(hid)
            if 11.40 <= lat <= 11.70 and 75.95 <= lon <= 76.22:
                wayanad.append((hid, lat, lon))
        except Exception:
            pass

    print(f"Wayanad hexes found: {len(wayanad)}")
    if not wayanad:
        print("ERROR: No hexes in Wayanad bbox. Seeding all hexes instead.")
        with get_db() as conn:
            rows = conn.execute("SELECT hex_id FROM hexes ORDER BY hex_id").fetchall()
        wayanad = [(r[0], 0, 0) for r in rows]

    ts = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        for i, (hid, lat, lon) in enumerate(wayanad):
            p = TERRAIN[i % len(TERRAIN)]
            r = RAIN[p["label"]]
            sf = {
                "slope": p["slope"], "slope_deg": p["slope"],
                "HAND_m": p["HAND"], "hand_m": p["HAND"],
                "soil_cohesion_kpa": p["soil_c"],
                "soil_friction_angle_deg": p["soil_phi"],
                "soil_depth_m": p["soil_depth"],
                "ndvi_mean": 0.48,
                "TWI": math.log(1.0 / max(math.tan(math.radians(p["slope"])), 0.01)),
                "elevation": 850.0 + p["slope"] * 12,
                "drainage_density": 2.1,
                "gsi_susceptibility_class": 3 if p["slope"] > 20 else 2,
                "historical_event_count_500m": 3 if p["label"] in ("Red", "Orange") else 0,
            }
            conn.execute(
                "UPDATE hexes SET static_features=? WHERE hex_id=?",
                (json.dumps(sf), hid)
            )
            dyn = dict(r)
            dyn["rain_intensity_mm_hr"] = r["rainfall_1h"]
            conn.execute(
                "INSERT INTO observations(hex_id,timestamp,provenance,dynamic_features) VALUES(?,?,?,?)",
                (hid, ts, "SIMULATED", json.dumps(dyn))
            )

            # Write risk score directly (no live weather fetch)
            label = p["label"]
            score = TIER_SCORES[label]
            conf  = TIER_CONF[label]
            fs    = TIER_FS[label]
            lead  = TIER_LEAD[label]
            contribs = [
                {"feature": "rainfall_24h", "contribution": score * 0.45},
                {"feature": "slope",        "contribution": score * 0.30},
                {"feature": "soil_saturation_ratio", "contribution": score * 0.15},
                {"feature": "HAND_m",       "contribution": score * 0.10},
            ]
            conn.execute(
                """INSERT INTO risk_scores
                   (hex_id, timestamp, risk_score, tier, confidence_score,
                    lead_time_min, lead_time_basis,
                    feature_contributions, data_source, provenance)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    hid, ts, score, label, conf,
                    lead, "forecast_projection" if lead else "no_red_crossing_in_forecast_window",
                    json.dumps(contribs),
                    "cached_demo", "SIMULATED",
                )
            )
            print(f"  {hid[:16]}... {label:6s} score={score:.0f}")

    print(f"\nDone. {len(wayanad)} Wayanad hexes seeded with varied tiers.")
    print("Hard-refresh the browser (Ctrl+Shift+R) to see the changes.")


if __name__ == "__main__":
    run()
