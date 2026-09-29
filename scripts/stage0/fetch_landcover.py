"""
scripts/stage0/fetch_landcover.py
Fetch ESA WorldCover 10m (2021) land-cover tiles for all 10 demo regions.

Stage 2 support script (Final.md §8.3 Tier 1 — ESA WorldCover).
Resolves the "land cover not found" warning from Stage 1 onboarding.

Downloads via the Copernicus STAC API → direct S3 tile URLs.
No account required. No rate limits on the S3 endpoint.

Output: data/landcover/<region_code>/worldcover_<region_code>.tif

Usage:
  python scripts/stage0/fetch_landcover.py
  python scripts/stage0/fetch_landcover.py --region wayanad-kl
"""

from __future__ import annotations

import argparse
import ssl
import sys
import time
import urllib.request
import json
from pathlib import Path

ROOT     = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "landcover"
UA       = "HydraSense/1.0 (SIH2026; hydrasense.sih2026@example.org)"
TIMEOUT  = 60

# All 10 region bboxes (matches pipeline.py ALL_REGIONS exactly)
REGIONS = {
    "wayanad-kl":    {"south": 11.40, "north": 11.70, "west": 75.95, "east": 76.22},
    "idukki-kl":     {"south":  9.80, "north": 10.20, "west": 76.80, "east": 77.10},
    "nilgiris-tn":   {"south": 11.20, "north": 11.55, "west": 76.55, "east": 76.90},
    "rudraprayag-uk":{"south": 30.40, "north": 30.70, "west": 78.85, "east": 79.10},
    "chamoli-uk":    {"south": 30.30, "north": 30.60, "west": 79.10, "east": 79.40},
    "kullu-hp":      {"south": 31.75, "north": 32.10, "west": 77.05, "east": 77.35},
    "mangan-sk":     {"south": 27.40, "north": 27.70, "west": 88.45, "east": 88.70},
    "darjeeling-wb": {"south": 26.90, "north": 27.20, "west": 88.10, "east": 88.40},
    "ribhoi-ml":     {"south": 25.70, "north": 26.00, "west": 91.80, "east": 92.10},
    "dhemaji-as":    {"south": 27.35, "north": 27.65, "west": 94.30, "east": 94.65},
}

# ESA WorldCover 2021 S3 tile index (10° x 10° tiles, named by SW corner)
# Format: N<lat>E<lon> or S<lat>W<lon>
# Source: https://esa-worldcover.org/en/data-access
STAC_SEARCH = "https://services.terrascope.be/stac/collections/urn:eop:VITO:ESA_WorldCover_10m_2021_AWS_V2/items"


def _get_json(url: str) -> dict | list | None:
    """HTTP GET returning parsed JSON, with SSL cert fallback for restricted networks."""
    for verify_ssl in (True, False):
        try:
            ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                return json.loads(r.read())
        except ssl.SSLError:
            if verify_ssl:
                continue   # retry without SSL verification
            return None
        except Exception:
            return None
    return None


def _stac_search_tiles(bbox: dict) -> list[str]:
    """
    Query STAC for ESA WorldCover tile download URLs covering the bbox.
    Returns a list of asset download URLs.
    """
    url = (
        f"{STAC_SEARCH}"
        f"?bbox={bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"
        f"&limit=10"
    )
    data = _get_json(url)
    if not data or "features" not in data:
        return []
    urls = []
    for feat in data["features"]:
        assets = feat.get("assets", {})
        # The ESA WorldCover tile is under the "ESA_WORLDCOVER_10M_MAP" asset
        for key in ("ESA_WORLDCOVER_10M_MAP", "map", "data"):
            asset = assets.get(key)
            if asset and "href" in asset:
                urls.append(asset["href"])
                break
    return urls


def _download(url: str, out_path: Path) -> tuple[bool, str]:
    """Download a URL to out_path. Returns (success, message)."""
    if out_path.exists() and out_path.stat().st_size > 1024:
        return True, f"Cached ({out_path.stat().st_size // 1024} KB)"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    for verify_ssl in (True, False):
        try:
            ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                body = r.read()
            elapsed = time.perf_counter() - t0
            out_path.write_bytes(body)
            return True, f"Downloaded {len(body)//1024} KB in {elapsed:.1f}s"
        except ssl.SSLError:
            if verify_ssl:
                continue
            return False, "SSL error even with verification disabled"
        except Exception as e:
            return False, str(e)
    return False, "Unknown download error"


WORLDCOVER_S3 = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                 "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
TILE_DEG = 3            # public WorldCover COGs are 3 x 3 degree tiles named by their SW corner


def _tile_name(lat_floor: int, lon_floor: int) -> str:
    return f"{'N' if lat_floor >= 0 else 'S'}{abs(lat_floor):02d}{'E' if lon_floor >= 0 else 'W'}{abs(lon_floor):03d}"


def _fetch_cog_window(region_code: str, bbox: dict, out_path: Path) -> tuple[bool, str]:
    """
    Read only the bbox window from the public WorldCover cloud-optimised GeoTIFFs on S3 (no STAC,
    no account, no full-tile download) and save it as a small GeoTIFF.  Handles a bbox that crosses
    tile edges by pasting each tile's window into one canvas.  Values are the real ESA classes; a
    tile that cannot be read leaves that part of the canvas at 0 (nodata) and is reported.
    """
    import math
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import from_bounds

    res = 1.0 / 12000.0                                    # 10 m ~ 8.333e-5 deg
    w, s_, e, n = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
    width, height = int(round((e - w) / res)), int(round((n - s_) / res))
    canvas = np.zeros((height, width), dtype=np.uint8)
    missing = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                      GDAL_HTTP_TIMEOUT="60"):
        for la in range(math.floor(s_ / TILE_DEG) * TILE_DEG, math.ceil(n / TILE_DEG) * TILE_DEG, TILE_DEG):
            for lo in range(math.floor(w / TILE_DEG) * TILE_DEG, math.ceil(e / TILE_DEG) * TILE_DEG, TILE_DEG):
                tile = _tile_name(la, lo)
                bw, bs, be, bn = max(w, lo), max(s_, la), min(e, lo + TILE_DEG), min(n, la + TILE_DEG)
                try:
                    with rasterio.open(WORLDCOVER_S3.format(tile=tile)) as src:
                        win = from_bounds(bw, bs, be, bn, src.transform)
                        a = src.read(1, window=win)
                    c0, r0 = int(round((bw - w) / res)), int(round((n - bn) / res))
                    h_, w_ = min(a.shape[0], height - r0), min(a.shape[1], width - c0)
                    canvas[r0:r0 + h_, c0:c0 + w_] = a[:h_, :w_]
                except Exception as exc:
                    missing.append(f"{tile}: {type(exc).__name__}")
    if missing and len(missing) == 1 and (canvas == 0).all():
        return False, "; ".join(missing)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", driver="GTiff", height=height, width=width, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(w, n, res, res), compress="lzw",
                       nodata=0) as dst:
        dst.write(canvas, 1)
    note = f" (tiles unreadable: {missing})" if missing else ""
    return True, f"window {width}x{height} px read from public COG{note}"


def fetch_region(region_code: str, bbox: dict) -> bool:
    out_path = DATA_DIR / region_code / f"worldcover_{region_code}.tif"
    if out_path.exists() and out_path.stat().st_size > 1024:
        print(f"  [{region_code}] Already cached: {out_path.name}")
        return True

    print(f"  [{region_code}] Reading WorldCover window from public S3 COG ...", end="", flush=True)
    ok, msg = _fetch_cog_window(region_code, bbox, out_path)
    print(f" {'OK' if ok else 'FAIL'}: {msg}")
    if ok:
        return True

    print(f"  [{region_code}] Searching STAC for tiles ...", end="", flush=True)
    tile_urls = _stac_search_tiles(bbox)
    if not tile_urls:
        print(" [FAIL] No tiles found via STAC — network/SSL issue")
        print(f"    Manual fallback: download from https://esa-worldcover.org/en/data-access")
        print(f"    Place tile at: {out_path}")
        return False

    # Download and merge tiles (if >1 tile, use rasterio merge)
    tile_paths = []
    for i, url in enumerate(tile_urls):
        tile_out = DATA_DIR / region_code / f"tile_{i:02d}.tif"
        ok, msg = _download(url, tile_out)
        if ok:
            tile_paths.append(tile_out)
        print(f"\n    Tile {i+1}/{len(tile_urls)}: {msg}")

    if not tile_paths:
        return False

    if len(tile_paths) == 1:
        # Single tile — just rename/copy
        import shutil
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(tile_paths[0], out_path)
        print(f"  [{region_code}] Saved: {out_path.name}")
        return True

    # Multiple tiles — merge with rasterio
    try:
        import rasterio
        from rasterio.merge import merge
        datasets = [rasterio.open(p) for p in tile_paths]
        mosaic, transform = merge(datasets)
        meta = datasets[0].meta.copy()
        meta.update({"driver": "GTiff", "height": mosaic.shape[1],
                     "width": mosaic.shape[2], "transform": transform})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_path, "w", **meta) as dst:
            dst.write(mosaic)
        for ds in datasets:
            ds.close()
        print(f"  [{region_code}] Merged {len(tile_paths)} tiles -> {out_path.name}")
        return True
    except Exception as e:
        print(f"  [{region_code}] Merge failed: {e} — keeping first tile only")
        import shutil
        shutil.copy(tile_paths[0], out_path)
        return True


def main(regions: list[str] | None = None) -> None:
    targets = regions or list(REGIONS.keys())
    invalid = [r for r in targets if r not in REGIONS]
    if invalid:
        print(f"Unknown region code(s): {invalid}")
        sys.exit(1)

    print("HydraSense Stage 2 — ESA WorldCover 10m Land-Cover Fetch")
    print("Reference: HydraSense_Final.md §8.3 (Tier 1) / Stage 2")
    print(f"Regions: {targets}\n")

    ok = fail = 0
    for rc in targets:
        success = fetch_region(rc, REGIONS[rc])
        if success:
            ok += 1
        else:
            fail += 1

    print(f"\n{'='*60}")
    print(f"  Downloaded/cached: {ok}  |  Failed: {fail}")
    if fail == 0:
        print("  All land-cover tiles available.")
        print("  Re-run: python -m backend.onboarding.pipeline --all --force")
        print("  to backfill land_use_class into all 10 region GeoPackages.")
    else:
        print("  Some tiles unavailable — land_use_class will be None for those regions.")
        print("  Confidence is not reduced for missing land cover (not in FS formula).")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch ESA WorldCover for HydraSense regions")
    parser.add_argument("--region", nargs="+", metavar="CODE",
                        help="Region code(s) to fetch. Default: all 10.")
    args = parser.parse_args()
    main(regions=args.region)
