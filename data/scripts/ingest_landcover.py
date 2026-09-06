"""
ingest_landcover.py — Pull ESA WorldCover 10m land cover + NDVI from public S3 bucket.

Implements: SRS.md Section 8 (Data Sources — land cover and NDVI rows).
Owner: guru-elight (Phase 1)

ESA WorldCover 2021 is available free, no signup, no API key from the public S3 bucket:
  s3://esa-worldcover/v200/2021/map/

The NDVI percentile composite (p50 — median annual NDVI) is available from the same project:
  s3://esa-worldcover/v200/2021/ndvi/

Both datasets are at 10m resolution (better than SRTM's 30m and NASA POWER's ~50km).

Output:
  data/landcover/landcover_wayanad.tif  — ESA WorldCover land use class (10m, clipped to bbox)
  data/landcover/ndvi_wayanad.tif       — NDVI p50 composite (10m, clipped to bbox)

These are inputs for Phase 3 static features:
  land_use_class, ndvi_mean (SRS.md Section 9 — static feature list)

HARD CONSTRAINT (CLAUDE.md / SRS.md Section 26):
  - On failure, this script exits with code 1. No silent fake data.
  - boto3 is used with --no-sign-request (anonymous, public bucket access).
"""

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Pilot cluster bounding box — Wayanad, Kerala (SRS.md Section 5)
# ESA WorldCover uses a tiling scheme; we identify the relevant tile(s)
# and clip to the pilot bbox during download.
# ---------------------------------------------------------------------------
BBOX = {
    "south": 11.490,
    "north": 11.540,
    "west":  76.030,
    "east":  76.070,
}

# ESA WorldCover S3 bucket (public, no credentials required)
# WorldCover uses 3°×3° tiles named by their SW corner: e.g. N09E075 covers lat 9-12, lon 75-78.
# The Wayanad cluster falls in tile N09E075.
ESA_S3_BUCKET = "esa-worldcover"
ESA_VERSION = "v200"
ESA_YEAR = "2021"

# Wayanad (lat ~11.5, lon ~76.0) -> tile SW corner: lat 9 (floored to multiple of 3), lon 75
TILE_LAT = 9    # SW corner latitude of the 3°×3° tile
TILE_LON = 75   # SW corner longitude of the 3°×3° tile

TILE_ID = f"N{abs(TILE_LAT):02d}{'S' if TILE_LAT < 0 else 'E'}{abs(TILE_LON):03d}"

# S3 keys for the relevant tile
LANDCOVER_S3_KEY = (
    f"{ESA_VERSION}/{ESA_YEAR}/map/"
    f"ESA_WorldCover_10m_{ESA_YEAR}_{ESA_VERSION}_{TILE_ID}_Map.tif"
)
NDVI_S3_KEY = (
    f"{ESA_VERSION}/{ESA_YEAR}/ndvi/"
    f"ESA_WorldCover_NominalNDVI_{ESA_YEAR}_{ESA_VERSION}_{TILE_ID}_NDVI_P50.tif"
)

# Output paths
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "landcover"
LANDCOVER_TILE = OUT_DIR / f"landcover_tile_{TILE_ID}.tif"
NDVI_TILE = OUT_DIR / f"ndvi_tile_{TILE_ID}.tif"
LANDCOVER_OUT = OUT_DIR / "landcover_wayanad.tif"
NDVI_OUT = OUT_DIR / "ndvi_wayanad.tif"


def check_dependencies() -> None:
    """Check that AWS CLI and GDAL (gdal_translate/gdalwarp) are available."""
    missing = []
    for tool in ["aws", "gdal_translate"]:
        result = subprocess.run(
            ["where", tool] if sys.platform == "win32" else ["which", tool],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            missing.append(tool)

    if missing:
        print(
            f"\nERROR: [ingest_landcover] Missing required tools: {missing}\n"
            "  Install AWS CLI: https://aws.amazon.com/cli/\n"
            "  Install GDAL: https://gdal.org/ or via conda: conda install -c conda-forge gdal\n"
            "  AWS CLI is used with --no-sign-request for anonymous public S3 access.",
            file=sys.stderr,
        )
        sys.exit(1)


def download_from_s3(s3_key: str, local_path: Path, description: str) -> None:
    """
    Download a file from the public ESA WorldCover S3 bucket.

    Uses AWS CLI with --no-sign-request (anonymous access, no credentials needed).
    Fails loudly if the download fails — no silent substitution.
    """
    s3_uri = f"s3://{ESA_S3_BUCKET}/{s3_key}"
    print(f"[ingest_landcover] Downloading {description}:")
    print(f"  Source: {s3_uri}")
    print(f"  Target: {local_path}")

    if local_path.exists():
        print(f"  -> Already exists, skipping download.")
        return

    result = subprocess.run(
        ["aws", "s3", "cp", s3_uri, str(local_path), "--no-sign-request"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(
            f"\nERROR: [ingest_landcover] Failed to download {description}:\n"
            f"  {result.stderr.strip()}\n"
            f"  Command: aws s3 cp {s3_uri} {local_path} --no-sign-request\n"
            "Do NOT substitute fake land cover data (CLAUDE.md hard constraint).",
            file=sys.stderr,
        )
        sys.exit(1)

    size_mb = local_path.stat().st_size / (1024 * 1024)
    print(f"  -> Downloaded ({size_mb:.1f} MB)")


def clip_to_bbox(input_tif: Path, output_tif: Path, description: str) -> None:
    """
    Clip a GeoTIFF to the pilot bounding box using gdal_translate (crop_to_cutline).

    gdal_translate with -projwin is the simplest approach for a lat/lon bbox clip.
    -projwin: ulx uly lrx lry (upper-left X, upper-left Y, lower-right X, lower-right Y)
    """
    print(f"[ingest_landcover] Clipping {description} to pilot bbox ...")

    ulx = BBOX["west"]
    uly = BBOX["north"]
    lrx = BBOX["east"]
    lry = BBOX["south"]

    result = subprocess.run(
        [
            "gdal_translate",
            "-projwin", str(ulx), str(uly), str(lrx), str(lry),
            "-projwin_srs", "EPSG:4326",
            "-of", "GTiff",
            "-co", "COMPRESS=LZW",
            str(input_tif),
            str(output_tif),
        ],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(
            f"\nERROR: [ingest_landcover] gdal_translate failed for {description}:\n"
            f"  {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)

    size_kb = output_tif.stat().st_size / 1024
    print(f"  -> Clipped to bbox ({size_kb:.1f} KB): {output_tif}")


def main() -> None:
    """
    Download ESA WorldCover land cover + NDVI tiles and clip to Wayanad pilot bbox.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    check_dependencies()

    print(f"\n[ingest_landcover] Tile ID: {TILE_ID}  (covers lat {TILE_LAT}°–{TILE_LAT+3}°, "
          f"lon {TILE_LON}°–{TILE_LON+3}°)")
    print(f"[ingest_landcover] Pilot bbox: "
          f"N{BBOX['north']} S{BBOX['south']} W{BBOX['west']} E{BBOX['east']}\n")

    # 1. Download full tile (10m, ~few hundred MB — clipped version will be tiny)
    download_from_s3(LANDCOVER_S3_KEY, LANDCOVER_TILE, "WorldCover land-use tile")
    download_from_s3(NDVI_S3_KEY, NDVI_TILE, "NDVI P50 tile")

    # 2. Clip to pilot bounding box
    clip_to_bbox(LANDCOVER_TILE, LANDCOVER_OUT, "land cover")
    clip_to_bbox(NDVI_TILE, NDVI_OUT, "NDVI")

    print()
    print("[ingest_landcover] Done.")
    print(f"  Land cover -> {LANDCOVER_OUT}")
    print(f"  NDVI       -> {NDVI_OUT}")
    print()
    print("Next: Phase 3 (static_features.py) will sample these per H3 hex for")
    print("  land_use_class and ndvi_mean (SRS.md Section 9).")
    print()
    print("NOTE: Full tile files are large (GeoTIFFs) and are gitignored (data/.gitignore).")
    print("      The clipped wayanad output files are also gitignored — re-run this script")
    print("      to regenerate if needed.")


if __name__ == "__main__":
    main()
