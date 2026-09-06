"""
ingest_rainfall_historical.py -- Pull archived hourly rainfall for historical event windows.

Implements: SRS.md Section 8 (Data Sources), Phase 1 supplement.
Owner: Dev A (Phase 1) / filed as Bug 3 fix from Phase 6 self-review.

WHY THIS EXISTS
---------------
ingest_rainfall.py uses Open-Meteo's forecast endpoint with past_days=92, which
covers only the last 3 months. historical_events.csv contains 30 events spanning
2009-2024. Every event older than 92 days from run date has all-NaN rainfall windows
in Phase 4's training parquet, making rainfall_1h/3h/6h/24h, rainfall_72h_antecedent,
and antecedent_precipitation_index useless for those positive samples.

THE DECISION (Phase 6 self-review, 2026-09-06)
-----------------------------------------------
Use Open-Meteo's Archive API (archive-api.open-meteo.com/v1/archive), which provides
hourly ERA5-reanalysis-based precipitation going back to 1940 at no cost with no API
key. For each historical event, we pull a 7-day window centred on the event date
(3 days before, event day, 3 days after) -- covering the full 72h antecedent window
needed for the earliest per-event snapshot (-72h before event time).

Output: data/weather/rainfall_historical.json
Format: identical to rainfall_current.json so Phase 4's load_rainfall_lookup()
can merge both files transparently.

Caveat: ERA5 hourly has ~0.25-degree (~28km) spatial resolution. For Wayanad's
4-village pilot cluster (within ~5km), this means all 4 village lookups resolve to
the same ERA5 grid point. That is acceptable -- we already note in SRS.md Section 8
that rainfall data has limited spatial granularity at this pilot scale. Do not
re-engineer this to sub-village resolution; it's explicitly out of scope.

HARD CONSTRAINTS (CLAUDE.md)
-----------------------------
- Timeout + loud failure; never silently substitute fake data.
- Data is labeled with data_source='open_meteo_archive_era5' -- never mislabeled
  as 'live' or 'observed' (it is ERA5 reanalysis, not a direct gauge measurement).
"""

import json
import sys
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Pilot locations (same as ingest_rainfall.py)
# ---------------------------------------------------------------------------
PILOT_LOCATIONS = [
    {"name": "Mundakkai",      "lat": 11.5185, "lon": 76.0524},
    {"name": "Chooralmala",    "lat": 11.5143, "lon": 76.0498},
    {"name": "Attamala",       "lat": 11.5220, "lon": 76.0570},
    {"name": "Punjirimattom",  "lat": 11.5100, "lon": 76.0450},
]

ARCHIVE_BASE    = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SECONDS = 20.0   # archive is slower than forecast; 20s for older date ranges
MAX_RETRIES     = 2      # one retry on timeout before aborting

EVENTS_CSV = Path(__file__).resolve().parents[2] / "data" / "events" / "historical_events.csv"
OUT_DIR    = Path(__file__).resolve().parents[2] / "data" / "weather"
OUT_PATH   = OUT_DIR / "rainfall_historical.json"

# Days to pull either side of each event date.
# 3 days before covers the full 72h antecedent window at the earliest snapshot
# (-72h before event). 3 days after gives buffer for phase-4 negative exclusion logic.
WINDOW_DAYS_BEFORE = 4   # 4 * 24 = 96h >= 72h antecedent + 24h margin
WINDOW_DAYS_AFTER  = 1


def load_event_dates() -> list[date]:
    """
    Read distinct event dates from historical_events.csv.
    Returns a sorted, deduplicated list of datetime.date objects.
    Exits loudly if the CSV does not exist.
    """
    if not EVENTS_CSV.exists():
        print(
            f"ERROR: {EVENTS_CSV} not found.\n"
            "  Commit historical_events.csv (Phase 4 deliverable) before running this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    dates: set[date] = set()
    with open(EVENTS_CSV) as f:
        header = True
        for line in f:
            if header:
                header = False
                continue
            parts = line.strip().split(",")
            if len(parts) < 3 or not parts[2].strip():
                continue
            raw_date = parts[2].strip()
            try:
                dates.add(date.fromisoformat(raw_date))
            except ValueError:
                print(f"  WARNING: Could not parse date '{raw_date}' -- skipping.", file=sys.stderr)

    result = sorted(dates)
    print(f"[ingest_rainfall_historical] {len(result)} distinct event dates from {EVENTS_CSV.name}")
    oldest = result[0] if result else None
    newest = result[-1] if result else None
    print(f"  Range: {oldest}  ->  {newest}")
    return result


def date_windows(event_dates: list[date]) -> list[tuple[date, date]]:
    """
    Merge per-event windows into a minimal list of (start, end) ranges,
    collapsing overlapping or adjacent windows to reduce API calls.

    Each event needs [event - WINDOW_DAYS_BEFORE, event + WINDOW_DAYS_AFTER].
    Events 7 days apart or less can share a window.
    """
    raw: list[tuple[date, date]] = []
    for d in event_dates:
        raw.append((
            d - timedelta(days=WINDOW_DAYS_BEFORE),
            d + timedelta(days=WINDOW_DAYS_AFTER),
        ))

    # Merge overlapping ranges
    merged: list[tuple[date, date]] = []
    for start, end in sorted(raw):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            # Extend the last range
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    return merged


def fetch_archive_window(
    lat: float,
    lon: float,
    name: str,
    start: date,
    end: date,
) -> dict[str, float | None]:
    """
    Fetch hourly ERA5 precipitation from Open-Meteo Archive for one location,
    one date window. Returns {iso8601_hour: precipitation_mm}.

    Data source: ERA5 reanalysis (~28km grid, hourly). Not a direct gauge
    measurement -- labeled as 'open_meteo_archive_era5' throughout.

    Raises RuntimeError on timeout or HTTP error -- never returns fake data.
    """
    params = {
        "latitude":  lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "hourly":     "precipitation",
        "timezone":   "UTC",
        "timeformat": "iso8601",
    }

    import time
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.get(ARCHIVE_BASE, params=params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            data   = resp.json()
            times  = data.get("hourly", {}).get("time", [])
            precip = data.get("hourly", {}).get("precipitation", [])
            return dict(zip(times, precip))
        except httpx.TimeoutException as e:
            last_exc = RuntimeError(
                f"[ingest_rainfall_historical] TIMEOUT after {TIMEOUT_SECONDS}s "
                f"fetching archive for {name} ({lat}, {lon}) "
                f"{start} -> {end} (attempt {attempt}/{MAX_RETRIES}).\n"
                "  Per CLAUDE.md: do not silently substitute fake data."
            )
            if attempt < MAX_RETRIES:
                wait = 5 * attempt
                print(f" timeout, retrying in {wait}s...", end=" ", flush=True)
                time.sleep(wait)
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"[ingest_rainfall_historical] HTTP {e.response.status_code} from archive "
                f"for {name} ({lat}, {lon}): {e.response.text}"
            )
        except httpx.RequestError as e:
            raise RuntimeError(
                f"[ingest_rainfall_historical] Network error for {name}: {e}"
            )
    raise last_exc  # all retries exhausted


def main() -> None:
    print("=" * 65)
    print("HydraSense -- Historical Rainfall Ingestion (Archive/ERA5)")
    print("Covers: Open-Meteo Archive, data back to 1940, free, no key.")
    print("=" * 65)
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1. Load event dates and compute fetch windows
    # -------------------------------------------------------------------------
    event_dates = load_event_dates()
    if not event_dates:
        print("ERROR: No event dates found -- nothing to fetch.", file=sys.stderr)
        sys.exit(1)

    windows = date_windows(event_dates)
    print(f"\n[ingest_rainfall_historical] Merged into {len(windows)} fetch window(s):")
    for s, e in windows:
        print(f"  {s}  ->  {e}  ({(e-s).days + 1} days)")

    # -------------------------------------------------------------------------
    # 2. Fetch per location per window, merge into one series per location
    # -------------------------------------------------------------------------
    # Structure: {location_name: {iso_hour: precipitation_mm}}
    merged_series: dict[str, dict[str, float | None]] = {
        loc["name"]: {} for loc in PILOT_LOCATIONS
    }

    for loc in PILOT_LOCATIONS:
        name = loc["name"]
        print(f"\n[ingest_rainfall_historical] Fetching archive for: {name}")
        for i, (start, end) in enumerate(windows, 1):
            print(f"  Window {i}/{len(windows)}: {start} -> {end} ...", end=" ", flush=True)
            try:
                hour_data = fetch_archive_window(loc["lat"], loc["lon"], name, start, end)
                merged_series[name].update(hour_data)
                print(f"{len(hour_data)} hours")
            except RuntimeError as e:
                print(f"\nERROR: {e}", file=sys.stderr)
                print(
                    "  Aborting -- partial data would silently corrupt the training set.\n"
                    "  Fix the connection issue and re-run. Per CLAUDE.md: no silent fakes.",
                    file=sys.stderr,
                )
                sys.exit(1)

        total_hours = len(merged_series[name])
        non_null = sum(1 for v in merged_series[name].values() if v is not None)
        print(f"  -> {name}: {total_hours} total hours, {non_null} non-null")

    # -------------------------------------------------------------------------
    # 3. Build output matching rainfall_current.json format exactly
    #    so Phase 4's load_rainfall_lookup() can merge both files.
    # -------------------------------------------------------------------------
    locations_out = []
    for loc in PILOT_LOCATIONS:
        name = loc["name"]
        series = merged_series[name]
        # Sort chronologically
        sorted_times  = sorted(series.keys())
        sorted_precip = [series[t] for t in sorted_times]

        locations_out.append({
            "location": name,
            "lat": loc["lat"],
            "lon": loc["lon"],
            # ERA5 reanalysis -- explicitly NOT labeled live/observed
            "data_source_note": (
                "ERA5 reanalysis via Open-Meteo Archive API (~28km grid). "
                "All 4 pilot villages resolve to the same grid point. "
                "Not a direct gauge measurement -- acceptable for training signal."
            ),
            "series": {
                "time":             sorted_times,
                "precipitation_mm": sorted_precip,
            },
        })

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "open_meteo_archive_era5",  # Never labeled 'live' or 'observed'
        "event_date_range": {
            "oldest_event": event_dates[0].isoformat(),
            "newest_event": event_dates[-1].isoformat(),
        },
        "window_days_before_event": WINDOW_DAYS_BEFORE,
        "window_days_after_event":  WINDOW_DAYS_AFTER,
        "locations": locations_out,
    }

    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    total_hours = sum(len(merged_series[loc["name"]]) for loc in PILOT_LOCATIONS)
    print(f"\n[ingest_rainfall_historical] Saved -> {OUT_PATH}")
    print(f"  Locations: {len(PILOT_LOCATIONS)}")
    print(f"  Total hour-slots: {total_hours}")
    print(f"  Event date range: {event_dates[0]}  ->  {event_dates[-1]}")
    print()
    print("  Next: re-run ml/features/event_centered_sampling.py (Phase 4)")
    print("  load_rainfall_lookup() merges rainfall_current.json + rainfall_historical.json")
    print("  automatically -- positive sample rainfall windows will now be non-null.")


if __name__ == "__main__":
    main()
