"""
scripts/stage0/prefetch_soilgrids.py
Stage 0 — Data-Access Lockdown (HydraSense_Final.md §16.2 / §8.2 / §7.3 / §14.3)

Pre-fetches bulk SoilGrids rasters via WCS (OGC Web Coverage Service) for
the demo shortlist bounding boxes.

Final.md §7.3 (verified):
    "SoilGrids is not a live-per-query layer. ISRIC's SoilGrids REST
     point-query API is officially paused. The soil/geotechnical layer must
     be fetched as a bulk raster via WCS or Google Earth Engine, per region
     bounding box, ahead of time."

Final.md §14.3 (demo shortlist):
    5-10 pre-tested locations spanning Himalayan, Western Ghats, and Northeast
    physiographic zones, each with a fully pre-fetched, cached dataset.

This script downloads four SoilGrids soil-property layers via WCS for each
demo shortlist bounding box, saving them as GeoTIFF files to:
    data/soil/soilgrids/<region_key>/<property>_<depth>.tif

Properties fetched (required for pedotransfer correlations — Final.md §9.2):
  - clay     (texture fraction → friction angle / cohesion estimate)
  - sand     (texture fraction → friction angle / cohesion estimate)
  - silt     (texture fraction)
  - bdod     (bulk density → soil unit weight γ)
  - soc      (soil organic carbon → used in some pedotransfer functions)

Depth: 0-5cm (surface) and 5-15cm (sub-surface) — two layers per property.

Usage:
  python scripts/stage0/prefetch_soilgrids.py
  python scripts/stage0/prefetch_soilgrids.py --region wayanad  # single region

WCS endpoint base: https://maps.isric.org/mapserv?map=/map/<property>.map
WCS docs: https://www.isric.org/explore/soilgrids/faq-soilgrids
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Demo shortlist bounding boxes (Final.md §14.3)
# ~15 km radius around each region anchor, aligned to 0.01° grid
# Physiographic coverage: Western Ghats (2), Himalayan (2), Northeast (1)
# ---------------------------------------------------------------------------
DEMO_SHORTLIST: dict[str, dict] = {
    "wayanad": {
        "label":   "Wayanad, Kerala (Western Ghats) — primary pilot",
        "bbox":    {"south": 11.40, "north": 11.70, "west": 75.95, "east": 76.22},
        "zone":    "western_ghats",
    },
    "idukki": {
        "label":   "Idukki, Kerala (Western Ghats)",
        "bbox":    {"south": 9.80,  "north": 10.20, "west": 76.80, "east": 77.10},
        "zone":    "western_ghats",
    },
    "rudraprayag": {
        "label":   "Rudraprayag, Uttarakhand (Himalayan)",
        "bbox":    {"south": 30.40, "north": 30.70, "west": 78.85, "east": 79.10},
        "zone":    "himalayan",
    },
    "chamoli": {
        "label":   "Chamoli (Gopeshwar), Uttarakhand (Himalayan)",
        "bbox":    {"south": 30.30, "north": 30.60, "west": 79.10, "east": 79.40},
        "zone":    "himalayan",
    },
    "ribhoi": {
        "label":   "Ribhoi (Nongpoh), Meghalaya (Northeast)",
        "bbox":    {"south": 25.70, "north": 26.00, "west": 91.80, "east": 92.10},
        "zone":    "northeast",
    },
}

# SoilGrids WCS properties — map file name → human label
# Each property name is used as the WCS map file: /map/<property>.map
SOILGRIDS_PROPERTIES: dict[str, str] = {
    "clay":  "Clay content (g/kg) — texture fraction for friction angle",
    "sand":  "Sand content (g/kg) — texture fraction for friction angle",
    "silt":  "Silt content (g/kg) — texture fraction",
    "bdod":  "Bulk density (cg/cm³) — converted to unit weight γ",
    "soc":   "Soil organic carbon (dg/kg) — pedotransfer correction",
}

# Depth layers to fetch (WCS coverage ID suffix format: <property>_<depth>_mean)
DEPTHS: list[str] = ["0-5cm", "5-15cm"]

# Output directory
ROOT     = Path(__file__).resolve().parents[2]
OUT_DIR  = ROOT / "data" / "soil" / "soilgrids"

TIMEOUT_SEC = 60    # raster downloads can be slow for larger bboxes

UA = "HydraSense-Stage0/1.0 (SIH2026; contact: hydrasense.sih2026@example.org)"


# ---------------------------------------------------------------------------
# WCS fetch
# ---------------------------------------------------------------------------

def build_wcs_url(property_name: str, depth: str, bbox: dict) -> str:
    """
    Build a SoilGrids WCS 2.0 GetCoverage URL for a given property, depth, and bbox.

    Coverage ID format: <PROPERTY>_<DEPTH>_mean  (e.g. clay_0-5cm_mean)
    WCS base:  https://maps.isric.org/mapserv?map=/map/<property>.map

    We request a GeoTIFF output in EPSG:4326 (lat/lon, same as our input bbox).
    """
    coverage_id = f"{property_name}_{depth}_mean"
    url = (
        f"https://maps.isric.org/mapserv?map=/map/{property_name}.map"
        f"&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
        f"&COVERAGEID={coverage_id}"
        f"&FORMAT=image/tiff"
        f"&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
        f"&SUBSET=Long({bbox['west']},{bbox['east']})"
        f"&SUBSET=Lat({bbox['south']},{bbox['north']})"
        f"&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
    )
    return url


def fetch_raster(url: str, out_path: Path) -> tuple[bool, str]:
    """
    Download a WCS raster GeoTIFF to out_path.
    Returns (success, message).
    """
    if out_path.exists():
        size_kb = out_path.stat().st_size / 1024
        return True, f"Already exists ({size_kb:.1f} KB) — skipped"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            body = resp.read()
            elapsed = time.perf_counter() - t0

        # Sanity check: a valid GeoTIFF starts with "II" (little-endian) or "MM" (big-endian)
        if len(body) < 100:
            return False, f"Response too small ({len(body)} bytes) — likely an error XML"
        magic = body[:4]
        if not (magic[:2] in (b"II", b"MM")):
            # Try to decode as text to see if it's an error message
            err_text = body[:200].decode("utf-8", errors="replace")
            return False, f"Not a valid GeoTIFF. Response start: {err_text[:100]}"

        out_path.write_bytes(body)
        size_kb = len(body) / 1024
        return True, f"Downloaded {size_kb:.1f} KB in {elapsed:.1f}s"

    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - t0
        err_body = e.read().decode("utf-8", errors="replace")[:150]
        return False, f"HTTP {e.code} after {elapsed:.1f}s: {err_body}"
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return False, f"Error after {elapsed:.1f}s: {exc}"


# ---------------------------------------------------------------------------
# Per-region pre-fetch
# ---------------------------------------------------------------------------

def prefetch_region(region_key: str, region_info: dict) -> dict:
    """
    Fetch all SoilGrids layers for one region.
    Returns a summary dict with counts of successes and failures.
    """
    label = region_info["label"]
    bbox  = region_info["bbox"]

    print(f"\n  [{region_key}]  {label}")
    print(f"  BBox: S={bbox['south']} N={bbox['north']} W={bbox['west']} E={bbox['east']}")

    region_dir = OUT_DIR / region_key
    region_dir.mkdir(parents=True, exist_ok=True)

    success = failure = skipped = 0

    for prop, prop_label in SOILGRIDS_PROPERTIES.items():
        for depth in DEPTHS:
            coverage = f"{prop}_{depth}_mean"
            out_path = region_dir / f"{coverage}.tif"
            url = build_wcs_url(prop, depth, bbox)

            print(f"    {coverage:<30} ...", end="", flush=True)
            ok, msg = fetch_raster(url, out_path)
            if ok:
                if "Already exists" in msg:
                    print(f" [SKIP] {msg}")
                    skipped += 1
                else:
                    print(f" [OK  ] {msg}")
                    success += 1
            else:
                print(f" [FAIL] {msg}")
                failure += 1

    return {"success": success, "skipped": skipped, "failure": failure}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(regions: Optional[list[str]] = None) -> None:  # noqa: F821
    targets = regions or list(DEMO_SHORTLIST.keys())
    invalid = [r for r in targets if r not in DEMO_SHORTLIST]
    if invalid:
        print(f"Unknown region key(s): {invalid}")
        print(f"Valid keys: {list(DEMO_SHORTLIST.keys())}")
        sys.exit(1)

    print("HydraSense Stage 0 — SoilGrids WCS Bulk Pre-fetch")
    print("Reference: HydraSense_Final.md §7.3 / §8.2 / §14.3 / §16.2")
    print(f"Output directory: {OUT_DIR}")
    print(f"Regions to pre-fetch: {targets}")
    print(f"Properties: {list(SOILGRIDS_PROPERTIES.keys())}  x  Depths: {DEPTHS}")
    print(f"Files per region: {len(SOILGRIDS_PROPERTIES) * len(DEPTHS)} GeoTIFF rasters\n")

    total_success = total_skip = total_fail = 0
    for rk in targets:
        summary = prefetch_region(rk, DEMO_SHORTLIST[rk])
        total_success += summary["success"]
        total_skip    += summary["skipped"]
        total_fail    += summary["failure"]

    print("\n" + "=" * 80)
    print("SOILGRIDS PRE-FETCH SUMMARY")
    print("=" * 80)
    print(f"  Downloaded (new):  {total_success}")
    print(f"  Already cached:    {total_skip}")
    print(f"  Failed:            {total_fail}")
    print("=" * 80)

    expected = len(targets) * len(SOILGRIDS_PROPERTIES) * len(DEPTHS)
    fetched  = total_success + total_skip

    if total_fail == 0:
        print(f"\n[OK]  All {fetched}/{expected} rasters available in {OUT_DIR}")
        print("    Stage 2 (FS parameter derivation from SoilGrids) is UNBLOCKED.")
    else:
        print(f"\n[WARN] {total_fail}/{expected} rasters failed.")
        print("    Check WCS connectivity (run verify_soilgrids_rest.py first).")
        print("    Regions with failed rasters will fall back to terrain-only FS estimate")
        print("    with confidence reduced and labeled 'soil parameters unavailable for")
        print("    live fetch' (Final.md §7.3 fallback behavior).")

    if total_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pre-fetch SoilGrids WCS rasters for HydraSense demo shortlist"
    )
    parser.add_argument(
        "--region",
        nargs="+",
        metavar="REGION_KEY",
        help=(
            f"Region key(s) to pre-fetch. "
            f"Choices: {list(DEMO_SHORTLIST.keys())}. "
            f"Default: all regions."
        ),
    )
    args = parser.parse_args()
    main(regions=args.region)
