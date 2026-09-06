"""
ingest_dem.py — Pull SRTM 30m DEM tiles from OpenTopography API.

Implements: SRS.md Section 8 (Data Sources — DEM row).
Owner: guru-elight (Phase 1)

OpenTopography provides free SRTM 30m (SRTMGL1) DEM access via REST API.
A free API key is required — sign up at https://opentopography.org/ (instant, no approval wait).

The API key is read from the OPENTOPO_API_KEY environment variable.
DO NOT hardcode the key in this file.

Bounding box covers Mundakkai, Chooralmala, Attamala, Punjirimattom (SRS.md Section 5).
Output: data/terrain/dem_wayanad.tif (GeoTIFF, SRTM 30m / ~1 arc-second)

This DEM is the primary input for Phase 3 (static feature engineering):
  slope_deg, aspect, elevation, TWI, TRI, distance_to_stream_m, drainage_density
  — all computed from this file using pysheds (SRS.md Section 7 frozen stack).

HARD CONSTRAINT (CLAUDE.md / SRS.md Section 26):
  - pysheds is the ONLY terrain library. Never substitute whitebox or richdem.
  - On failure, this script exits with code 1 and a clear error. No silent fake data.
"""

import os
import sys
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Pilot cluster bounding box — Wayanad, Kerala
# Covers all 4 named villages with a small buffer (SRS.md Section 5).
# Format: south, north, west, east (decimal degrees, WGS84)
# ---------------------------------------------------------------------------
BBOX = {
    "south": 11.490,
    "north": 11.540,
    "west":  76.030,
    "east":  76.070,
}

# OpenTopography API settings
OPENTOPO_BASE = "https://portal.opentopography.org/API"
DEM_TYPE = "SRTMGL1"     # SRTM 30m (1 arc-second), global coverage includes Wayanad
OUTPUT_FORMAT = "GTiff"
TIMEOUT_SECONDS = 60.0   # DEM download can be large — 60s timeout

# Output path
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "terrain"
OUT_FILE = OUT_DIR / "dem_wayanad.tif"


def get_api_key() -> str:
    """
    Read the OpenTopography API key from the OPENTOPO_API_KEY environment variable.
    Exits with a clear error if the variable is not set.
    """
    key = os.environ.get("OPENTOPO_API_KEY", "").strip()
    if not key:
        print(
            "\nERROR: OPENTOPO_API_KEY environment variable is not set.\n"
            "  1. Sign up (free, instant) at https://opentopography.org/\n"
            "  2. Get your API key from the user dashboard.\n"
            "  3. Set it: $env:OPENTOPO_API_KEY = 'your_key_here'  (PowerShell)\n"
            "             export OPENTOPO_API_KEY='your_key_here'  (bash)\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def fetch_dem(api_key: str) -> bytes:
    """
    Fetch SRTM 30m GeoTIFF from OpenTopography for the pilot bounding box.

    Returns raw GeoTIFF bytes.
    Exits with code 1 on failure — no silent substitution (CLAUDE.md constraint).
    """
    url = f"{OPENTOPO_BASE}/globaldem"
    params = {
        "demtype":    DEM_TYPE,
        "south":      BBOX["south"],
        "north":      BBOX["north"],
        "west":       BBOX["west"],
        "east":       BBOX["east"],
        "outputFormat": OUTPUT_FORMAT,
        "API_Key":    api_key,
    }

    print(
        f"[ingest_dem] Requesting {DEM_TYPE} for bbox "
        f"({BBOX['south']},{BBOX['west']}) -> ({BBOX['north']},{BBOX['east']}) ..."
    )
    print(f"[ingest_dem] Timeout: {TIMEOUT_SECONDS}s")

    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.TimeoutException:
        print(
            f"\nERROR: [ingest_dem] TIMEOUT after {TIMEOUT_SECONDS}s from OpenTopography.\n"
            "The DEM fetch can be slow — check your connection or try again.\n"
            "Do NOT substitute synthetic elevation data (CLAUDE.md hard constraint).",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        # OpenTopography returns a plain-text error body on bad key/bbox
        err_body = e.response.text[:500]
        print(
            f"\nERROR: [ingest_dem] HTTP {e.response.status_code} from OpenTopography:\n"
            f"  {err_body}\n"
            "Check your OPENTOPO_API_KEY and bounding box.",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.RequestError as e:
        print(
            f"\nERROR: [ingest_dem] Network error: {e}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Sanity-check the response is actually a GeoTIFF
    content_type = response.headers.get("content-type", "")
    if "tiff" not in content_type.lower() and len(response.content) < 1000:
        # Possibly an error page returned with 200
        print(
            f"\nERROR: [ingest_dem] Unexpected response from OpenTopography "
            f"(content-type: {content_type!r}, size: {len(response.content)} bytes).\n"
            f"Body preview: {response.text[:300]!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    return response.content


def main() -> None:
    """
    Download SRTM 30m DEM for the Wayanad pilot cluster and save as GeoTIFF.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    api_key = get_api_key()
    dem_bytes = fetch_dem(api_key)

    OUT_FILE.write_bytes(dem_bytes)
    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"\n[ingest_dem] Saved DEM -> {OUT_FILE}  ({size_kb:.1f} KB)")
    print("[ingest_dem] Done.")
    print()
    print("Next: run Phase 3 (static_features.py) to compute slope, TWI, TRI etc. from this file.")
    print("      pysheds is the ONLY terrain library — per CLAUDE.md hard constraint.")


if __name__ == "__main__":
    main()
