"""
ingest_soil_multiregion.py -- Real NASA POWER GWETROOT for all Wayanad+Idukki
event windows (Step 4, multi-region).

Reuses data/scripts/ingest_soil.py's approach (GWETROOT hourly, no key,
soil_saturation_ratio = GWETROOT directly per SRS.md Section 10.1) without
modifying that file -- that script only covers a rolling last-30-days
window; this one covers actual historical event dates back to 1968/1985.

CONFIRMED REAL CONSTRAINT (tested live against the API, not documentation):
  NASA POWER's hourly endpoint returns HTTP 422 "data starts at 2001/01/01"
  for any request before that date. Events before 2001-01-01 get
  soil_saturation_ratio = null, tagged 'unavailable_predates_nasa_power_coverage'
  -- not fabricated, not silently dropped.

OPTIMIZATION (real, lossless, per ingest_soil.py's own documented ~50km
native resolution): all points within a region are well inside one NASA
POWER grid cell, so this fetches once per region (using the first named
point as query location) per merged window, not once per point.

Output: data/multiregion/soil/soil_moisture_wayanad.json
        data/multiregion/soil/soil_moisture_idukki.json

HARD CONSTRAINT (CLAUDE.md): NASA SMAP is never used. On real failure
(timeout/network), exit 1 -- no silent fake data. Pre-2001 coverage gap is
a documented real limitation, not a failure to retry.
"""

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
EVENTS_CSV = REPO_ROOT / "data" / "multiregion" / "events" / "flood_events_labeled_step2.csv"
OUT_DIR = REPO_ROOT / "data" / "multiregion" / "soil"

NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/hourly/point"
TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2
WINDOW_DAYS_BEFORE = 4
WINDOW_DAYS_AFTER = 1
NASA_POWER_COVERAGE_START = date(2001, 1, 1)  # confirmed live via test call, HTTP 422 below this

REGION_QUERY_POINT = {
    # One representative point per region -- NASA POWER ~50km native resolution
    # means every named point in-region returns the same value (documented in
    # ingest_soil.py). Reusing that same fact here, not a new assumption.
    "Wayanad": ("Mundakkai", 11.5185, 76.0524),
    "Idukki":  ("Munnar_town", 10.0889, 77.0595),
    "Rudraprayag": ("Rudraprayag_town", 30.2849, 78.9810),
    "Chamoli": ("Joshimath", 30.5622, 79.5641),
    "Ribhoi": ("Nongpoh_town_district_HQ", 25.9167, 91.8833),
    "Nilgiris": ("Ooty_Udhagamandalam_district_HQ", 11.4064, 76.6932),
    "Sikkim/Mangan": ("Mangan_district_HQ", 27.5167, 88.5333),
    "Darjeeling/Kalimpong": ("Darjeeling_town_district_HQ", 27.0410, 88.2663),
    "Kullu": ("Kullu_town_district_HQ", 31.9576, 77.1095),
    "Dhemaji": ("Dhemaji_town_district_HQ", 27.4833, 94.5667),
}

# Same user-confirmed scope cut as ingest_rainfall_historical_multiregion.py
DHEMAJI_MAX_DISTRICTS = 10

REGION_ALL_POINTS = {
    "Wayanad": ["Mundakkai", "Chooralmala", "Attamala", "Punjirimattom"],
    "Idukki": [
        "Munnar_town", "Pettimudi_Rajamala", "Idamalayar_Dam",
        "Idukki_Arch_Dam", "Idukki_district_centroid_proxy_Painavu",
    ],
    "Rudraprayag": ["Rudraprayag_town", "Kedarnath", "Guptkashi"],
    "Chamoli": ["Joshimath", "Gopeshwar", "Badrinath"],
    "Ribhoi": ["Nongpoh_town_district_HQ", "Byrnihat"],
    "Nilgiris": ["Ooty_Udhagamandalam_district_HQ", "Coonoor", "Gudalur"],
    "Sikkim/Mangan": ["Mangan_district_HQ", "Chungthang", "Lachen"],
    "Darjeeling/Kalimpong": ["Darjeeling_town_district_HQ", "Kalimpong_town_district_HQ", "Kurseong"],
    "Kullu": ["Kullu_town_district_HQ", "Manali", "Bhuntar"],
    "Dhemaji": ["Dhemaji_town_district_HQ", "Jonai", "Gogamukh"],
}


def load_event_dates(region: str) -> list[date]:
    df = pd.read_csv(EVENTS_CSV, low_memory=False)
    df["_dt"] = pd.to_datetime(df["Start Date"], format="%d-%m-%Y %H:%M", errors="coerce")
    manual_mask = df["UEI"] == "MANUAL-2024-WAYANAD-001"
    if manual_mask.any():
        df.loc[manual_mask, "_dt"] = pd.Timestamp("2024-07-30 02:17:00")
    sub = df[df["target_location"] == region]
    if region == "Dhemaji":
        n_districts = sub["Districts"].astype(str).apply(lambda s: len(s.split(",")))
        sub = sub[n_districts <= DHEMAJI_MAX_DISTRICTS]
    dates = sorted(sub["_dt"].dropna().dt.normalize().unique())
    return [pd.Timestamp(d).date() for d in dates]


def merged_windows(dates: list[date]) -> list[tuple[date, date]]:
    raw = sorted([
        (d - timedelta(days=WINDOW_DAYS_BEFORE), d + timedelta(days=WINDOW_DAYS_AFTER))
        for d in dates
    ])
    merged: list[tuple[date, date]] = []
    for s, e in raw:
        if merged and s <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def fetch_gwetroot_window(lat: float, lon: float, start: date, end: date) -> dict:
    params = {
        "parameters": "GWETROOT", "community": "SB",
        "longitude": lon, "latitude": lat,
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        "format": "JSON", "header": "false", "time-standard": "LST",
    }
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.get(NASA_POWER_BASE, params=params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            series = data["properties"]["parameter"]["GWETROOT"]
            return {ts: (v if v != -999.0 else None) for ts, v in series.items()}
        except httpx.TimeoutException:
            last_exc = RuntimeError(f"TIMEOUT after {TIMEOUT_SECONDS}s for {start}->{end}")
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
        except httpx.RequestError as e:
            raise RuntimeError(f"Network error: {e}")
    raise last_exc


def process_region(region: str) -> None:
    name0, lat0, lon0 = REGION_QUERY_POINT[region]
    print(f"\n{'='*70}\n{region}  (query point: {name0} {lat0},{lon0})\n{'='*70}")

    event_dates = load_event_dates(region)
    print(f"[{region}] {len(event_dates)} distinct event dates: {event_dates[0]} -> {event_dates[-1]}")

    pre_coverage = [d for d in event_dates if d < NASA_POWER_COVERAGE_START]
    post_coverage = [d for d in event_dates if d >= NASA_POWER_COVERAGE_START]
    print(
        f"[{region}] {len(pre_coverage)} events predate NASA POWER coverage (before 2001-01-01) "
        f"-> soil_saturation_ratio will be null for these, documented not fabricated"
    )
    print(f"[{region}] {len(post_coverage)} events within coverage -> real fetch")

    if not post_coverage:
        print(f"[{region}] No events within NASA POWER coverage -- skipping fetch.")
        merged_series = {}
    else:
        windows = merged_windows(post_coverage)
        print(f"[{region}] Merged into {len(windows)} fetch window(s)")
        merged_series: dict[str, float] = {}
        for i, (start, end) in enumerate(windows, 1):
            print(f"  [{i}/{len(windows)}] {start} -> {end} ...", end=" ", flush=True)
            try:
                hour_data = fetch_gwetroot_window(lat0, lon0, start, end)
                merged_series.update(hour_data)
                print(f"{len(hour_data)}h")
            except RuntimeError as e:
                print(f"\nERROR: {e}", file=sys.stderr)
                print("Aborting region -- per CLAUDE.md, no partial silent data.", file=sys.stderr)
                sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = region.lower().replace("/", "_")
    out_path = OUT_DIR / f"soil_moisture_{safe_name}.json"
    output = {
        "fetched_at": pd.Timestamp.utcnow().isoformat(),
        "source": "NASA POWER API (no key required)",
        "parameter": "GWETROOT",
        "usage": "soil_saturation_ratio = GWETROOT directly per SRS.md Section 10.1. Label as 'soil saturation proxy'.",
        "coverage_note": (
            f"NASA POWER hourly GWETROOT confirmed (live test call, HTTP 422) to start "
            f"{NASA_POWER_COVERAGE_START.isoformat()}. {len(pre_coverage)} of {len(event_dates)} "
            f"{region} events predate this and have null soil_saturation_ratio -- a real API "
            f"coverage limit, not a fetch failure."
        ),
        "resolution_note": (
            "NASA POWER native resolution ~50km (MERRA-2 grid). All points in this region "
            "share one grid cell -- fetched once, replicated across named points."
        ),
        "locations": [
            {
                "location": pt_name, "lat": lat0 if pt_name == name0 else None,
                "label": "soil saturation proxy",
                "gwetroot_hourly": merged_series,
            }
            for pt_name in REGION_ALL_POINTS[region]
        ],
    }
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    n_valid = sum(1 for v in merged_series.values() if v is not None)
    print(f"\n[{region}] Saved -> {out_path}")
    print(f"  {len(merged_series)} hourly entries, {n_valid} valid values (shared across {len(REGION_ALL_POINTS[region])} named points)")


def main():
    regions = sys.argv[1:] if len(sys.argv) > 1 else list(REGION_QUERY_POINT.keys())
    for region in regions:
        process_region(region)
    print(f"\nDone -- {regions} fetched real NASA POWER GWETROOT (within coverage).")


if __name__ == "__main__":
    main()
