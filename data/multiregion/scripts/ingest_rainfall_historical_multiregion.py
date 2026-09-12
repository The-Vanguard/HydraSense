"""
ingest_rainfall_historical_multiregion.py -- Real ERA5 archive rainfall for
all 265 real IMD events (150 Wayanad + 115 Idukki incl. the 2024 manual add),
1968-2023, via Open-Meteo Archive API.

Reuses the exact approach of data/scripts/ingest_rainfall_historical.py
(window merging, retry-on-timeout, data_source labeling) without modifying
that file -- lives in data/multiregion/ instead.

OPTIMIZATION (not a scope cut -- a real, lossless dedup): ERA5 hourly has
~0.25-degree (~28km) spatial resolution -- this is already noted in the
original ingest_rainfall_historical.py's own docstring for Wayanad's 4
villages, which all resolve to one ERA5 grid cell. Two points inside the
same 0.25-deg grid cell return bit-identical values from the API regardless
of how many times you ask, so fetching once per unique grid cell (not once
per named point) is a real API-call reduction with zero loss of information.
This script computes that grouping explicitly and replicates results across
points sharing a cell.

Output:
  data/multiregion/weather/rainfall_historical_wayanad.json
  data/multiregion/weather/rainfall_historical_idukki.json
Format matches data/weather/rainfall_historical.json so any future
load_rainfall_lookup()-style code can merge them the same way.

HARD CONSTRAINT (CLAUDE.md): timeout + retry, never silently substitute
fake data. data_source is always 'open_meteo_archive_era5' -- never
mislabeled as live/observed.
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
OUT_DIR = REPO_ROOT / "data" / "multiregion" / "weather"

ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 2
WINDOW_DAYS_BEFORE = 4
WINDOW_DAYS_AFTER = 1
ERA5_GRID_DEG = 0.25  # ERA5 native resolution -- points in the same cell get identical values

REGION_POINTS = {
    "Wayanad": {
        "Mundakkai":     (11.5185, 76.0524),
        "Chooralmala":   (11.5143, 76.0498),
        "Attamala":      (11.5220, 76.0570),
        "Punjirimattom": (11.5100, 76.0450),
    },
    "Idukki": {
        "Munnar_town":                             (10.0889, 77.0595),
        "Pettimudi_Rajamala":                       (10.1683, 77.0114),
        "Idamalayar_Dam":                           (10.2062, 76.8496),
        "Idukki_Arch_Dam":                          (9.8447, 76.9744),
        "Idukki_district_centroid_proxy_Painavu":   (9.8497, 76.9744),
    },
    "Rudraprayag": {
        "Rudraprayag_town": (30.2849, 78.9810),
        "Kedarnath":        (30.7346, 79.0669),
        "Guptkashi":        (30.5333, 79.0833),
    },
    "Chamoli": {
        "Joshimath":  (30.5622, 79.5641),
        "Gopeshwar":  (30.3936, 79.3159),
        "Badrinath":  (30.7433, 79.4938),
    },
    "Ribhoi": {
        "Nongpoh_town_district_HQ": (25.9167, 91.8833),
        "Byrnihat":                 (25.9667, 91.8667),
    },
    "Nilgiris": {
        "Ooty_Udhagamandalam_district_HQ": (11.4064, 76.6932),
        "Coonoor":                         (11.3530, 76.7959),
        "Gudalur":                         (11.5000, 76.4833),
    },
    "Sikkim/Mangan": {
        "Mangan_district_HQ": (27.5167, 88.5333),
        "Chungthang":         (27.6167, 88.6333),
        "Lachen":             (27.7167, 88.5500),
    },
    "Darjeeling/Kalimpong": {
        "Darjeeling_town_district_HQ": (27.0410, 88.2663),
        "Kalimpong_town_district_HQ":  (27.0670, 88.4700),
        "Kurseong":                    (26.8809, 88.2809),
    },
    "Kullu": {
        "Kullu_town_district_HQ": (31.9576, 77.1095),
        "Manali":                 (32.2432, 77.1892),
        "Bhuntar":                (31.8830, 77.1520),
    },
    "Dhemaji": {
        "Dhemaji_town_district_HQ": (27.4833, 94.5667),
        "Jonai":                    (27.7500, 95.1167),
        "Gogamukh":                 (27.3500, 94.3500),
    },
}

# Dhemaji-specific, user-confirmed scope cut: 90/202 raw Dhemaji rows list
# 10+ Assam districts at once (state-wide monsoon summary records, 62%
# riverine_flood, 0% flash_flood) -- barely "Dhemaji events." Restricted to
# the 112 locally-scoped rows (<=10 districts listed) per user decision.
DHEMAJI_MAX_DISTRICTS = 10


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    return (
        (lat // ERA5_GRID_DEG) * ERA5_GRID_DEG,
        (lon // ERA5_GRID_DEG) * ERA5_GRID_DEG,
    )


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


def fetch_archive_window(lat: float, lon: float, start: date, end: date) -> dict:
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "hourly": "precipitation", "timezone": "UTC", "timeformat": "iso8601",
    }
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.get(ARCHIVE_BASE, params=params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            times = data.get("hourly", {}).get("time", [])
            precip = data.get("hourly", {}).get("precipitation", [])
            return dict(zip(times, precip))
        except httpx.TimeoutException:
            last_exc = RuntimeError(f"TIMEOUT after {TIMEOUT_SECONDS}s for ({lat},{lon}) {start}->{end}")
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
        except httpx.RequestError as e:
            # Transient connection resets ("forcibly closed by remote host") are real
            # but not permanent -- retry these too, same as timeouts, instead of
            # aborting the whole region on one network blip.
            last_exc = RuntimeError(f"Network error: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(3 * attempt)
    raise last_exc


def process_region(region: str) -> None:
    points = REGION_POINTS[region]
    print(f"\n{'='*70}\n{region}\n{'='*70}")

    event_dates = load_event_dates(region)
    print(f"[{region}] {len(event_dates)} distinct event dates: {event_dates[0]} -> {event_dates[-1]}")

    windows = merged_windows(event_dates)
    print(f"[{region}] Merged into {len(windows)} fetch window(s)")

    # Group points by shared ERA5 grid cell (real, lossless dedup)
    cell_to_points: dict[tuple, list[str]] = {}
    for name, (lat, lon) in points.items():
        cell = grid_cell(lat, lon)
        cell_to_points.setdefault(cell, []).append(name)
    print(f"[{region}] {len(points)} named points -> {len(cell_to_points)} unique ERA5 grid cell(s):")
    for cell, names in cell_to_points.items():
        print(f"    cell {cell}: {names}")

    total_calls = len(windows) * len(cell_to_points)
    print(f"[{region}] Total real API calls needed: {len(windows)} windows x {len(cell_to_points)} cells = {total_calls}")

    # Fetch once per (cell, window), using the first point in that cell as the query location
    cell_series: dict[tuple, dict[str, float]] = {c: {} for c in cell_to_points}
    call_n = 0
    for cell, names in cell_to_points.items():
        query_lat, query_lon = points[names[0]]
        for i, (start, end) in enumerate(windows, 1):
            call_n += 1
            print(f"  [{call_n}/{total_calls}] cell{cell} window {i}/{len(windows)}: {start}->{end} ...", end=" ", flush=True)
            try:
                hour_data = fetch_archive_window(query_lat, query_lon, start, end)
                cell_series[cell].update(hour_data)
                print(f"{len(hour_data)}h")
            except RuntimeError as e:
                print(f"\nERROR: {e}", file=sys.stderr)
                print("Aborting region -- per CLAUDE.md, no partial silent data.", file=sys.stderr)
                sys.exit(1)

    # Replicate cell series across all named points sharing that cell
    locations_out = []
    for name, (lat, lon) in points.items():
        cell = grid_cell(lat, lon)
        series = cell_series[cell]
        sorted_times = sorted(series.keys())
        sorted_precip = [series[t] for t in sorted_times]
        locations_out.append({
            "location": name, "lat": lat, "lon": lon,
            "data_source_note": (
                "ERA5 reanalysis via Open-Meteo Archive API (~28km/0.25deg grid). "
                f"Shares ERA5 grid cell {cell} with: {[n for n in cell_to_points[cell] if n != name]}. "
                "Not a direct gauge measurement."
            ),
            "series": {"time": sorted_times, "precipitation_mm": sorted_precip},
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = region.lower().replace("/", "_")
    out_path = OUT_DIR / f"rainfall_historical_{safe_name}.json"
    output = {
        "fetched_at": pd.Timestamp.utcnow().isoformat(),
        "data_source": "open_meteo_archive_era5",
        "event_date_range": {"oldest_event": str(event_dates[0]), "newest_event": str(event_dates[-1])},
        "window_days_before_event": WINDOW_DAYS_BEFORE,
        "window_days_after_event": WINDOW_DAYS_AFTER,
        "locations": locations_out,
    }
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    total_hours = sum(len(cell_series[grid_cell(*points[l["location"]])]) for l in locations_out)
    print(f"\n[{region}] Saved -> {out_path}")
    for loc in locations_out:
        n = len(loc["series"]["time"])
        non_null = sum(1 for v in loc["series"]["precipitation_mm"] if v is not None)
        print(f"  {loc['location']:16s} {n:5d} hours, {non_null:5d} non-null")


def main():
    regions = sys.argv[1:] if len(sys.argv) > 1 else list(REGION_POINTS.keys())
    for region in regions:
        process_region(region)
    print(f"\nDone -- {regions} fetched with real ERA5 archive data.")


if __name__ == "__main__":
    main()
