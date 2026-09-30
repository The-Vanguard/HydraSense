"""
scripts/stage0/fetch_cop30_dem.py -- stage a district DEM from the Copernicus GLO-30 open data on AWS.

No API key is needed: the 1x1 degree Cloud-Optimised GeoTIFFs are public
(https://copernicus-dem-30m.s3.amazonaws.com).  Only the window covering the bbox is read.  The result is
written where the onboarding pipeline looks for a cached DEM:

    data/terrain/<region>/dem_cop30_<region>.tif

  py -3.12 scripts/stage0/fetch_cop30_dem.py --region wayanad-kl --bbox 11.35,12.10,75.65,76.55
  (bbox = south,north,west,east)

Licence: Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018,
provided under COPERNICUS by the European Union and ESA; free for any use with attribution.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://copernicus-dem-30m.s3.amazonaws.com"


def tile_url(lat: int, lon: int) -> str:
    ns = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00"
    ew = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00"
    name = f"Copernicus_DSM_COG_10_{ns}_{ew}_DEM"
    return f"/vsicurl/{BASE}/{name}/{name}.tif"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True)
    ap.add_argument("--bbox", required=True, help="south,north,west,east")
    a = ap.parse_args()
    s, n, w, e = (float(x) for x in a.bbox.split(","))
    import rasterio
    from rasterio.merge import merge

    urls = [tile_url(la, lo) for la in range(math.floor(s), math.floor(n) + 1)
            for lo in range(math.floor(w), math.floor(e) + 1)]
    srcs = []
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        for u in urls:
            try:
                srcs.append(rasterio.open(u))
            except Exception as exc:                 # ocean tiles do not exist
                print(f"  skip {u.split('/')[-1]}: {exc}")
        if not srcs:
            sys.exit("no Copernicus tiles for this bbox")
        mosaic, transform = merge(srcs, bounds=(w, s, e, n))
        meta = srcs[0].meta.copy()
        for r in srcs:
            r.close()
    meta.update(driver="GTiff", height=mosaic.shape[1], width=mosaic.shape[2], transform=transform,
                compress="deflate", tiled=True)
    out = ROOT / "data" / "terrain" / a.region / f"dem_cop30_{a.region}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **meta) as dst:
        dst.write(mosaic)
        dst.update_tags(source="Copernicus DEM GLO-30 (AWS open data)", bbox=a.bbox)
    print(f"wrote {out.relative_to(ROOT)}  {mosaic.shape[2]}x{mosaic.shape[1]} px  "
          f"elev {float(mosaic.min()):.0f}..{float(mosaic.max()):.0f} m")


if __name__ == "__main__":
    main()
