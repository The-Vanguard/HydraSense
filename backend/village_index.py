"""
backend/village_index.py -- which village does a hex belong to?

Built from each region's village footprints (data/regions/{region}.gpkg, layer "villages") so the UI can
show a place name instead of a raw H3 id.  A hex outside every footprint gets the nearest village centroid,
flagged `nearest=True`.  Cached per region until the GeoPackage file changes.
"""
from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
GPKG_DIR = ROOT / "data" / "regions"

_CACHE: dict[str, tuple[float, dict, list]] = {}      # region -> (mtime, {hex: (vid, name)}, [(lat, lon, vid, name)])
_LOCK = threading.Lock()


def _build(region_code: str):
    import geopandas as gpd
    from backend import village_rollup as vr
    path = GPKG_DIR / f"{region_code}.gpkg"
    vg = gpd.read_file(path, layer="villages")
    by_hex: dict[str, tuple[str, str]] = {}
    centroids: list[tuple[float, float, str, str]] = []
    for _, r in vg.iterrows():
        vid, name = str(r["village_id"]), str(r.get("name") or r["village_id"])
        try:
            cells, _ = vr.footprint_hexes(r.geometry)
        except Exception:
            cells = set()
        for h in cells:
            by_hex.setdefault(h, (vid, name))
        try:
            c = r.geometry.centroid
            centroids.append((c.y, c.x, vid, name))
        except Exception:
            pass
    return by_hex, centroids


def _region_index(region_code: str):
    path = GPKG_DIR / f"{region_code}.gpkg"
    if not region_code or not path.exists():
        return None
    mtime = path.stat().st_mtime
    with _LOCK:
        hit = _CACHE.get(region_code)
        if hit and hit[0] == mtime:
            return hit
    try:
        by_hex, centroids = _build(region_code)
    except Exception:
        return None
    with _LOCK:
        _CACHE[region_code] = (mtime, by_hex, centroids)
    return _CACHE[region_code]


def village_for_hex(region_code: str, hex_id: str) -> Optional[dict]:
    """{village_id, name, nearest} for a hex, or None if the region has no village layer."""
    idx = _region_index(region_code)
    if idx is None:
        return None
    _, by_hex, centroids = idx
    if hex_id in by_hex:
        vid, name = by_hex[hex_id]
        return {"village_id": vid, "name": name, "nearest": False}
    if not centroids:
        return None
    import h3
    lat, lon = h3.cell_to_latlng(hex_id)
    k = math.cos(math.radians(lat))
    best = min(centroids, key=lambda c: (c[0] - lat) ** 2 + ((c[1] - lon) * k) ** 2)
    return {"village_id": best[2], "name": best[3], "nearest": True}
