"""
scripts/onboard_pending.py -- onboard every region that has a real, district-scale DEM.

For each region: (1) stage the cached real inputs where the pipeline expects them (copy, never
move), (2) fetch ESA WorldCover land cover, (3) run the standard onboarding pipeline with --force.

  * wayanad-kl is SKIPPED: its only DEM (data/terrain/dem_wayanad.tif) is a ~4x5 km tile, so the
    pipeline would compute terrain for a fraction of the district and label the rest missing.
  * Soil: SoilGrids rasters are cached for wayanad, idukki, ribhoi, rudraprayag, chamoli only.
    Other regions run with the pipeline's flagged fallback soil parameters (soil_data_source).
  * Network: Nominatim, Overpass, Copernicus/ESA S3.  Each stage logs failures; a failed region
    does not stop the others.
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# region_code -> short name used by the earlier multi-region ingest scripts
CACHED_DEM = {
    "ribhoi-ml": "ribhoi", "idukki-kl": "idukki", "nilgiris-tn": "nilgiris",
    "rudraprayag-uk": "rudraprayag", "chamoli-uk": "chamoli", "kullu-hp": "kullu",
    "mangan-sk": "sikkim", "darjeeling-wb": "darjeeling", "dhemaji-as": "dhemaji",
}
SKIPPED = {"wayanad-kl": "only a ~4x5 km DEM tile exists; district-scale DEM needs an OpenTopography key"}


def stage_inputs(code: str, short: str) -> list[str]:
    notes = []
    dem_src = ROOT / "data" / "multiregion" / "terrain" / f"dem_{short}.tif"
    dem_dst = ROOT / "data" / "terrain" / code / f"dem_srtmgl1_{code}.tif"
    if dem_src.exists() and not dem_dst.exists():
        dem_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dem_src, dem_dst)
        notes.append("DEM staged")
    soil_src = ROOT / "data" / "soil" / "soilgrids" / short
    soil_dst = ROOT / "data" / "soil" / "soilgrids" / code
    if soil_src.is_dir() and not soil_dst.exists():
        shutil.copytree(soil_src, soil_dst)
        notes.append("soil staged")
    elif not soil_src.is_dir():
        notes.append("no cached soil (fallback parameters will be used and flagged)")
    return notes


def main():
    from backend.onboarding.pipeline import run_pipeline, REGION_BY_CODE
    only = sys.argv[1:]
    summary = []
    for code, short in CACHED_DEM.items():
        if only and code not in only:
            continue
        t0 = time.time()
        reg = REGION_BY_CODE[code]
        print(f"\n##### {code}: {stage_inputs(code, short)}", flush=True)
        lc = subprocess.run([sys.executable, str(ROOT / "scripts" / "stage0" / "fetch_landcover.py"),
                             "--region", code], capture_output=True, text=True, cwd=ROOT)
        print("  landcover:", (lc.stdout.strip().splitlines() or ["(no output)"])[-1][:150],
              "| rc", lc.returncode, flush=True)
        try:
            r = run_pipeline(query=reg["query"], region_code=code, force_rerun=True)
            summary.append((code, r.success, r.hex_count, round(time.time() - t0)))
        except Exception as exc:                                    # keep going
            print(f"  !! {code} failed: {type(exc).__name__}: {exc}", flush=True)
            summary.append((code, False, 0, round(time.time() - t0)))
    for code, why in SKIPPED.items():
        print(f"skipped {code}: {why}")
    print("\n=== SUMMARY ===")
    for code, ok, n, secs in summary:
        print(f"  {code:16s} {'ok ' if ok else 'FAIL'} hexes={n:6d}  {secs}s")


if __name__ == "__main__":
    main()
