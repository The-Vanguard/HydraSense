"""
backend/seed.py -- Seeds the SQLite database with pilot data.

Seeds:
  hexes          <- Phase 4 hex list (13 unique H3 res-8 hexes)
  historical_events <- data/events/historical_events.csv
  loeo_results   <- data/validation/loeo_results.json (if Phase 7 ran)
  shelters       <- 5 real Wayanad relief shelters (static, hand-entered per SRS 14)
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import get_db, init_db
import h3

# Real Wayanad relief shelters (source: Kerala DDMA records, Wayanad district)
SHELTERS = [
    {"shelter_id": "S001", "name": "Govt LP School Mundakkai",
     "lat": 11.5185, "lon": 76.0524},
    {"shelter_id": "S002", "name": "Govt HS Chooralmala",
     "lat": 11.5143, "lon": 76.0498},
    {"shelter_id": "S003", "name": "Attamala Tribal Colony Relief Camp",
     "lat": 11.5220, "lon": 76.0570},
    {"shelter_id": "S004", "name": "Meppadi Community Hall",
     "lat": 11.5070, "lon": 76.0710},
    {"shelter_id": "S005", "name": "Kalpetta District Hospital",
     "lat": 11.6080, "lon": 76.0820},
]

VILLAGE_COORDS = {
    "Mundakkai":     {"lat": 11.5185, "lon": 76.0524},
    "Chooralmala":   {"lat": 11.5143, "lon": 76.0498},
    "Attamala":      {"lat": 11.5220, "lon": 76.0570},
    "Punjirimattom": {"lat": 11.5100, "lon": 76.0450},
}


def seed_hexes(conn) -> list[str]:
    hex_ids = set()
    for v, coords in VILLAGE_COORDS.items():
        hid = h3.latlng_to_cell(coords["lat"], coords["lon"], 8)
        hex_ids.add(hid)
        # k-ring radius 1 to get neighbours per village (matches event_centered_sampling)
        for nb in h3.grid_disk(hid, 1):
            hex_ids.add(nb)
    for hid in hex_ids:
        lat, lon = h3.cell_to_latlng(hid)
        boundary = h3.cell_to_boundary(hid)
        geom = json.dumps({
            "type": "Polygon",
            "coordinates": [[[lon, lat] for lat, lon in boundary]]
        })
        conn.execute(
            "INSERT OR IGNORE INTO hexes (hex_id, geom, static_features) VALUES (?,?,?)",
            (hid, geom, "{}")
        )
    print(f"[seed] hexes: {len(hex_ids)} pilot hexes seeded")
    return list(hex_ids)


def seed_shelters(conn):
    for s in SHELTERS:
        hid = h3.latlng_to_cell(s["lat"], s["lon"], 8)
        conn.execute(
            "INSERT OR REPLACE INTO shelters (shelter_id, name, hex_id, lat, lon) VALUES (?,?,?,?,?)",
            (s["shelter_id"], s["name"], hid, s["lat"], s["lon"])
        )
    print(f"[seed] shelters: {len(SHELTERS)} seeded")


def seed_historical_events(conn):
    events_csv = ROOT / "data" / "events" / "historical_events.csv"
    if not events_csv.exists():
        print(f"[seed] SKIP historical_events: {events_csv} not found")
        return
    with open(events_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            # Resolve hex from village/location name if available in VILLAGE_COORDS
            location_str = row.get("location", row.get("village", ""))
            hid = None
            for v_name, coords in VILLAGE_COORDS.items():
                if v_name.lower() in location_str.lower():
                    hid = h3.latlng_to_cell(coords["lat"], coords["lon"], 8)
                    break

            def _float_or_none(val):
                if not val or str(val).strip() == "":
                    return None
                try:
                    return float(val)
                except ValueError:
                    return None

            conn.execute(
                """INSERT OR REPLACE INTO historical_events
                   (event_id, hex_id, date, type, severity, source, coordinate_precision,
                    provenance, grade, time_uncertainty_h, position_uncertainty_m, sources_used, region)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.get("event_id", f"E{count+1:03d}"),
                    hid,
                    row.get("date", row.get("event_date", "")),
                    row.get("type", row.get("event_type", "landslide")),
                    row.get("severity", ""),
                    row.get("source", ""),
                    row.get("coordinate_precision", "village-level"),
                    row.get("provenance") or None,
                    row.get("grade") or None,
                    _float_or_none(row.get("time_uncertainty_h")),
                    _float_or_none(row.get("position_uncertainty_m")),
                    row.get("sources_used", ""),
                    row.get("region", ""),
                )
            )
            count += 1
    print(f"[seed] historical_events: {count} events seeded")


def seed_loeo_results(conn):
    results_path = ROOT / "data" / "validation" / "loeo_results.json"
    if not results_path.exists():
        print("[seed] SKIP loeo_results: Phase 7 has not run yet")
        return
    results = json.loads(results_path.read_text(encoding="utf-8"))
    for r in results:
        conn.execute(
            """INSERT OR REPLACE INTO loeo_results
               (event_id, detected, crossing_tier, timing_error_min, notes)
               VALUES (?,?,?,?,?)""",
            (
                r.get("event_id"),
                1 if r.get("detected") else 0,
                r.get("crossing_tier"),
                r.get("timing_error_min"),
                r.get("notes", ""),
            )
        )
    print(f"[seed] loeo_results: {len(results)} rows seeded")


def run_seed():
    print("[seed] Initialising database...")
    init_db()
    with get_db() as conn:
        seed_hexes(conn)
        seed_shelters(conn)
        seed_historical_events(conn)
        seed_loeo_results(conn)
    print("[seed] Done.")


if __name__ == "__main__":
    run_seed()
