"""
ingest_dem_generic.py -- Parameterized SRTM 30m DEM fetch for any multi-region
location, reusing the exact OpenTopography API pattern from
data/scripts/ingest_dem.py (Wayanad, untouched) and
data/multiregion/scripts/ingest_dem_idukki.py (Idukki, first generalization).

Usage:
  OPENTOPO_API_KEY=... python ingest_dem_generic.py <name> <south> <north> <west> <east>

Output: data/multiregion/terrain/dem_<name>.tif

HARD CONSTRAINT (CLAUDE.md): no synthetic elevation data, ever. Exit 1 on failure.
"""

import os
import sys
from pathlib import Path

import httpx

OPENTOPO_BASE = "https://portal.opentopography.org/API"
DEM_TYPE = "SRTMGL1"
OUTPUT_FORMAT = "GTiff"
TIMEOUT_SECONDS = 60.0
OUT_DIR = Path(__file__).resolve().parents[1] / "terrain"


def get_api_key() -> str:
    key = os.environ.get("OPENTOPO_API_KEY", "").strip()
    if not key:
        print("ERROR: OPENTOPO_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    return key


def main():
    if len(sys.argv) != 6:
        print("Usage: ingest_dem_generic.py <name> <south> <north> <west> <east>", file=sys.stderr)
        sys.exit(1)
    name, south, north, west, east = sys.argv[1:]
    south, north, west, east = float(south), float(north), float(west), float(east)

    api_key = get_api_key()
    params = {
        "demtype": DEM_TYPE, "south": south, "north": north, "west": west, "east": east,
        "outputFormat": OUTPUT_FORMAT, "API_Key": api_key,
    }
    print(f"[ingest_dem_generic:{name}] Requesting {DEM_TYPE} for bbox ({south},{west}) -> ({north},{east}) ...")
    try:
        response = httpx.get(f"{OPENTOPO_BASE}/globaldem", params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.TimeoutException:
        print(f"ERROR: [ingest_dem_generic:{name}] TIMEOUT after {TIMEOUT_SECONDS}s.", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: [ingest_dem_generic:{name}] HTTP {e.response.status_code}: {e.response.text[:500]}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"ERROR: [ingest_dem_generic:{name}] Network error: {e}", file=sys.stderr)
        sys.exit(1)

    content_type = response.headers.get("content-type", "")
    if "tiff" not in content_type.lower() and len(response.content) < 1000:
        print(f"ERROR: [ingest_dem_generic:{name}] Unexpected response: {response.text[:300]!r}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"dem_{name.lower()}.tif"
    out_path.write_bytes(response.content)
    print(f"[ingest_dem_generic:{name}] Saved -> {out_path}  ({out_path.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
