"""
ingest_soil.py — Pull soil moisture (GWETROOT) from NASA POWER API.

Implements: SRS.md Section 8 (Data Sources — soil moisture row), Section 10.1 (FS model).
Owner: Dev A (Phase 1)

NASA POWER (Prediction of Worldwide Energy Resources) provides free, no-key-required
access to modelled soil-moisture parameters derived from MERRA-2 reanalysis.

FROZEN FORMULA (SRS.md Section 10.1):
  soil_saturation_ratio = GWETROOT
  GWETROOT is NASA POWER's "Root Zone Soil Wetness" — already a 0–1 fraction of saturation.
  No derivation or conversion is needed. Use the value as-is.

KNOWN LIMITATION (SRS.md Section 8 — must be in code and UI):
  NASA POWER's native resolution is ~50 km (MERRA-2 grid). This is a real, permanent accuracy
  ceiling — not a build defect. The value is spread to each H3 hex by nearest-grid assignment
  (Phase 3). In the UI this MUST be labeled "soil saturation proxy" — never described as a
  village-level measurement. NASA SMAP is explicitly excluded (CLAUDE.md).

Output: data/soil/soil_moisture.json — GWETROOT time series for each pilot location.

HARD CONSTRAINT (CLAUDE.md / SRS.md Section 26):
  - NASA SMAP is NEVER used (requires Earthdata login + HDF5/NetCDF processing).
  - On failure, this script exits with code 1. No silent fake data.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Pilot cluster locations — Wayanad, Kerala (SRS.md Section 5)
# NASA POWER is queried per point; its ~50km grid means all 4 points will
# return nearly identical values — this is expected and documented above.
# ---------------------------------------------------------------------------
PILOT_LOCATIONS = [
    {"name": "Mundakkai",      "lat": 11.5185, "lon": 76.0524},
    {"name": "Chooralmala",    "lat": 11.5143, "lon": 76.0498},
    {"name": "Attamala",       "lat": 11.5220, "lon": 76.0570},
    {"name": "Punjirimattom",  "lat": 11.5100, "lon": 76.0450},
]

# NASA POWER API settings
NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/hourly/point"
TIMEOUT_SECONDS = 30.0

# Pull 30 days of hourly GWETROOT — covers antecedent history for training features.
# POWER data has a ~5-day lag, so end date is set back to be safe.
END_DATE = date.today() - timedelta(days=5)
START_DATE = END_DATE - timedelta(days=30)

# Output
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "soil"
OUT_FILE = OUT_DIR / "soil_moisture.json"


def fetch_gwetroot(lat: float, lon: float, name: str) -> dict:
    """
    Fetch hourly GWETROOT from NASA POWER for a single lat/lon.

    GWETROOT = Root Zone Soil Wetness (0–1 fraction).
    Per SRS.md Section 10.1: soil_saturation_ratio = GWETROOT directly.
    No conversion formula is applied — the value is used as-is.

    Raises RuntimeError on timeout or HTTP error — never returns fake data.
    """
    params = {
        "parameters": "GWETROOT",
        "community": "SB",              # Sustainable Buildings community — includes soil params
        "longitude": lon,
        "latitude": lat,
        "start": START_DATE.strftime("%Y%m%d"),
        "end": END_DATE.strftime("%Y%m%d"),
        "format": "JSON",
        "header": "false",
        "time-standard": "LST",
    }

    print(f"  [ingest_soil] Fetching GWETROOT for {name} ({lat}, {lon}) ...")
    print(f"    Period: {START_DATE} -> {END_DATE}")

    try:
        response = httpx.get(NASA_POWER_BASE, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.TimeoutException:
        raise RuntimeError(
            f"[ingest_soil] TIMEOUT after {TIMEOUT_SECONDS}s fetching NASA POWER "
            f"for {name} ({lat}, {lon}). Check connection and retry. "
            "Do NOT substitute fake soil data (CLAUDE.md hard constraint)."
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"[ingest_soil] HTTP {e.response.status_code} from NASA POWER for {name}: "
            f"{e.response.text[:300]}"
        )
    except httpx.RequestError as e:
        raise RuntimeError(
            f"[ingest_soil] Network error from NASA POWER for {name}: {e}"
        )

    data = response.json()

    # Extract GWETROOT time series from NASA POWER's nested response format
    try:
        gwetroot_series = data["properties"]["parameter"]["GWETROOT"]
    except KeyError:
        raise RuntimeError(
            f"[ingest_soil] Unexpected NASA POWER response structure for {name}. "
            f"Keys found: {list(data.get('properties', {}).get('parameter', {}).keys())}"
        )

    # NASA POWER uses -999 as a fill value for missing data — surface these explicitly
    missing_count = sum(1 for v in gwetroot_series.values() if v == -999.0)
    if missing_count > 0:
        print(
            f"    WARNING: {missing_count} missing values (fill=-999) in GWETROOT "
            f"for {name}. These will appear as null in the output JSON."
        )

    # Convert fill values to null for clean downstream handling
    cleaned = {
        ts: (v if v != -999.0 else None)
        for ts, v in gwetroot_series.items()
    }

    return {
        "location": name,
        "lat": lat,
        "lon": lon,
        # IMPORTANT: This label must propagate to the UI wherever this value appears.
        # SRS.md Section 10.1 and Section 8: label as "soil saturation proxy" —
        # NEVER as "village-level measurement" (CLAUDE.md hard constraint).
        "label": "soil saturation proxy",
        "source": "NASA POWER GWETROOT (~50km native resolution — external-data-only estimate)",
        "parameter": "GWETROOT",
        # FROZEN FORMULA (SRS.md Section 10.1):
        # soil_saturation_ratio = GWETROOT  (no further conversion)
        "soil_saturation_ratio_field": "GWETROOT",
        "start_date": START_DATE.isoformat(),
        "end_date": END_DATE.isoformat(),
        "resolution_note": (
            "NASA POWER native resolution is ~50km (MERRA-2 grid). "
            "This is a known, permanent accuracy ceiling per SRS.md Section 8. "
            "All pilot hexes receive the same nearest-grid value — not village-level data."
        ),
        "gwetroot_hourly": cleaned,
    }


def main() -> None:
    """
    Fetch GWETROOT soil moisture data for all pilot locations and save to data/soil/.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    for loc in PILOT_LOCATIONS:
        try:
            record = fetch_gwetroot(loc["lat"], loc["lon"], loc["name"])
        except RuntimeError as e:
            print(f"\nERROR: {e}", file=sys.stderr)
            print(
                "\nPipeline aborted. NASA POWER is required — NASA SMAP is NOT used "
                "(CLAUDE.md hard constraint: NASA SMAP is explicitly excluded).",
                file=sys.stderr,
            )
            sys.exit(1)

        n_values = len(record["gwetroot_hourly"])
        n_valid = sum(1 for v in record["gwetroot_hourly"].values() if v is not None)
        print(f"    -> {n_values} hourly entries, {n_valid} valid values")
        results.append(record)

    out = {
        "fetched_at": str(date.today()),
        "source": "NASA POWER API (no key required)",
        "parameter": "GWETROOT",
        "usage": (
            "soil_saturation_ratio = GWETROOT directly per SRS.md Section 10.1. "
            "No conversion formula. Label as 'soil saturation proxy' in all UI components."
        ),
        "locations": results,
    }

    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n[ingest_soil] Saved -> {OUT_FILE}")
    print("[ingest_soil] Done.")
    print()
    print("REMINDER: This data must always be labeled 'soil saturation proxy' in the UI.")
    print("  Native resolution: ~50km. Not village-level data (SRS.md Section 8).")


if __name__ == "__main__":
    main()
