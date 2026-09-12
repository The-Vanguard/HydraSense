"""
ingest_dem_idukki.py -- Pull SRTM 30m DEM for the Idukki high-range event cluster.

Multi-region companion to data/scripts/ingest_dem.py (Wayanad pilot, untouched --
Phase 1 is owned by guru-elight; this file lives in data/multiregion/ instead of
modifying the original).

Reuses the exact OpenTopography SRTMGL1 API call pattern from ingest_dem.py.

Bounding box: Munnar / Devikulam taluk high range, Idukki district, Kerala.
Covers every point we actually have real-source detail for tonight:
  - Idukki Arch Reservoir / Idukki Dam        (~9.845 N, 76.975 E)
  - Idamalayar Reservoir                       (~10.20 N, 76.85 E)
  - Munnar town                                (~10.089 N, 77.060 E)
  - Pettimudi / Rajamala (2020 landslide site)  (~10.10 N, 77.13 E)
Not the whole of Idukki district (~5,000 sq km, far beyond what our event
coordinates justify) -- this ~50km x 50km box is the smallest box that
honestly covers the actual confirmed points, not a guess at district extent.

Output: data/multiregion/terrain/dem_idukki.tif (GeoTIFF, SRTM 30m)

HARD CONSTRAINT (CLAUDE.md):
  - pysheds is the ONLY terrain library for anything computed FROM this DEM.
  - On failure, exit 1 with a clear error. No synthetic elevation data, ever.
"""

import os
import sys
from pathlib import Path

import httpx

BBOX = {
    "south": 9.80,
    "north": 10.35,
    "west":  76.78,
    "east":  77.25,
}

OPENTOPO_BASE = "https://portal.opentopography.org/API"
DEM_TYPE = "SRTMGL1"
OUTPUT_FORMAT = "GTiff"
TIMEOUT_SECONDS = 60.0

OUT_DIR = Path(__file__).resolve().parents[1] / "terrain"
OUT_FILE = OUT_DIR / "dem_idukki.tif"


def get_api_key() -> str:
    key = os.environ.get("OPENTOPO_API_KEY", "").strip()
    if not key:
        print(
            "\nERROR: OPENTOPO_API_KEY environment variable is not set.\n"
            "  1. Sign up (free, instant) at https://opentopography.org/\n"
            "  2. Get your API key from the user dashboard.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def fetch_dem(api_key: str) -> bytes:
    url = f"{OPENTOPO_BASE}/globaldem"
    params = {
        "demtype":      DEM_TYPE,
        "south":        BBOX["south"],
        "north":        BBOX["north"],
        "west":         BBOX["west"],
        "east":         BBOX["east"],
        "outputFormat": OUTPUT_FORMAT,
        "API_Key":      api_key,
    }

    print(
        f"[ingest_dem_idukki] Requesting {DEM_TYPE} for bbox "
        f"({BBOX['south']},{BBOX['west']}) -> ({BBOX['north']},{BBOX['east']}) ..."
    )
    print(f"[ingest_dem_idukki] Timeout: {TIMEOUT_SECONDS}s")

    try:
        response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.TimeoutException:
        print(
            f"\nERROR: [ingest_dem_idukki] TIMEOUT after {TIMEOUT_SECONDS}s from OpenTopography.\n"
            "Do NOT substitute synthetic elevation data (CLAUDE.md hard constraint).",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        err_body = e.response.text[:500]
        print(
            f"\nERROR: [ingest_dem_idukki] HTTP {e.response.status_code} from OpenTopography:\n"
            f"  {err_body}\n"
            "Check your OPENTOPO_API_KEY and bounding box.",
            file=sys.stderr,
        )
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"\nERROR: [ingest_dem_idukki] Network error: {e}", file=sys.stderr)
        sys.exit(1)

    content_type = response.headers.get("content-type", "")
    if "tiff" not in content_type.lower() and len(response.content) < 1000:
        print(
            f"\nERROR: [ingest_dem_idukki] Unexpected response from OpenTopography "
            f"(content-type: {content_type!r}, size: {len(response.content)} bytes).\n"
            f"Body preview: {response.text[:300]!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    return response.content


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    api_key = get_api_key()
    dem_bytes = fetch_dem(api_key)

    OUT_FILE.write_bytes(dem_bytes)
    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"\n[ingest_dem_idukki] Saved DEM -> {OUT_FILE}  ({size_kb:.1f} KB)")
    print("[ingest_dem_idukki] Done.")


if __name__ == "__main__":
    main()
