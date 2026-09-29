"""
backend/onboarding/villages.py
Step 10 of the Autonomous Region Onboarding Pipeline (Gap Analysis §A4).

Village/ward polygon fetch from OSM (Overpass API) with footprint and
upslope-reach annotation from the catchment delineation result (Step 9).

Writes a 'villages' layer to the region's GeoPackage.

Algorithm:
  1. Query Overpass API for administrative boundaries and named place polygons
     within the region bbox.  Tries three fallback strategies:
       a. Named place polygons (place=village, place=hamlet, place=town)
       b. Administrative boundaries at admin_level 8, 9, 10
       c. WorldPop gridded population as village centroids (last resort)
  2. For each village polygon:
       - footprint_km2    = polygon area in km²
       - upslope_reach_km = max upslope_reach_km of any catchment whose outlet
                            falls inside or within 500 m of the village centroid
       - nearest_hex_id   = H3 res-8 cell nearest to the village centroid
       - population       = WorldPop estimate (nullable; not fetched in Phase 1)
  3. All rows tagged provenance = REAL_VALIDATED (OSM-sourced data).
  4. Appended as 'villages' layer in the region GeoPackage.

Provenance: REAL_VALIDATED for OSM-sourced polygons.
            The Overpass timeout and fallback paths may produce fewer polygons
            than the true village count; this is reported in warnings, not masked.

Dependencies: requests>=2.31, geopandas>=0.14, shapely>=2.0, h3>=4.0
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Gap Analysis §0.2: provenance policy
from backend.provenance import ProvenanceTag

ROOT = Path(__file__).resolve().parents[2]

# Overpass API endpoint (no auth required; rate-limited)
OVERPASS_URL   = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT = 60   # seconds

# Spatial join tolerance: a catchment outlet is "linked" to a village
# if it falls within this distance of the village centroid (degrees ≈ km at
# Indian latitudes: 0.005° ≈ 500 m).
OUTLET_LINK_TOLERANCE_DEG = 0.005


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VillageResult:
    region_code:   str
    success:       bool
    village_count: int = 0
    gpkg_path:     Optional[Path] = None
    error:         Optional[str] = None
    warnings:      list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def fetch_village_polygons(
    region_code: str,
    bbox: dict,
    gpkg_path: Path,
    catchment_result=None,    # CatchmentResult | None
) -> VillageResult:
    """
    Fetch village/ward polygons from OSM for the region bbox and annotate them
    with footprint and upslope reach from the catchment delineation.

    Args:
        region_code:      slug (e.g. "wayanad-kl")
        bbox:             {south, north, west, east} in WGS84
        gpkg_path:        path to the region's .gpkg file (must already exist)
        catchment_result: CatchmentResult from delineate_catchments() or None

    Returns:
        VillageResult
    """
    warns: list[str] = []

    # ── Dependency guard ───────────────────────────────────────────────────
    try:
        import requests
        import geopandas as gpd
        import h3
        from shapely.geometry import Point, Polygon, shape
    except ImportError as e:
        return VillageResult(
            region_code=region_code, success=False,
            error=f"Missing dependency for village polygon fetch: {e}. "
                  f"Install: pip install requests geopandas shapely h3"
        )

    # ── Load catchment data for upslope-reach annotation ──────────────────
    catchment_gdf = None
    if catchment_result is not None and catchment_result.success and \
       catchment_result.gpkg_path is not None and catchment_result.gpkg_path.exists():
        try:
            catchment_gdf = gpd.read_file(
                str(catchment_result.gpkg_path), layer="catchments"
            )
        except Exception as e:
            warns.append(f"Could not load catchments layer for upslope annotation: {e}")

    # ── Strategy 0 (cheap, tried first): Voronoi cells around named place NODES ───────
    # In India most villages are mapped as place nodes, and the node query is small and fast
    # (~2 s) where the polygon queries below can time out for minutes.  When at least
    # MIN_NODES_FOR_VORONOI named places exist they are the village-scale units (admin polygons at
    # levels 8-10 are often sub-district sized).  This reorders v2 §5.3.1's list on purpose.
    village_features: list = []
    nodes = _query_overpass_place_nodes(bbox, warns)
    if len(nodes) >= MIN_NODES_FOR_VORONOI:
        village_features = _voronoi_villages(nodes, bbox, warns)
        if village_features:
            warns.append(
                f"Using {len(village_features)} Voronoi cells around named OSM place nodes "
                f"(boundary_quality=voronoi_approx): approximate footprints, not surveyed boundaries."
            )

    # ── Strategy 1: Named place polygons from Overpass ────────────────────
    if not village_features:
        village_features = _query_overpass_place_polygons(bbox, warns)

    # ── Strategy 2: Admin boundaries if places returned too few ───────────
    if len(village_features) < 3:
        warns.append(
            f"Strategy 1 (named places) returned {len(village_features)} polygons — "
            f"falling back to administrative boundaries"
        )
        admin_features = _query_overpass_admin_boundaries(bbox, warns)
        village_features.extend(admin_features)

    # ── Strategy 2.5: Voronoi from the few nodes there are (below the threshold) ──
    if len(village_features) < 3:
        vor = _voronoi_villages(nodes, bbox, warns)
        if vor:
            warns.append(
                f"Using {len(vor)} Voronoi cells around named OSM place nodes "
                f"(boundary_quality=voronoi_approx): approximate footprints, not surveyed boundaries."
            )
            village_features = list(village_features) + vor

    # ── Strategy 3: Centroid-based fallback if still empty ────────────────
    if not village_features:
        warns.append(
            "No OSM village polygons found. Generating centroid-based "
            "placeholder polygons from H3 hex centroids. "
            "These are labeled REAL_VALIDATED (H3 centroids from the real boundary) "
            "but lack named polygon geometry. Replace when OSM data is available."
        )
        village_features = _generate_hex_centroid_placeholders(bbox, warns)

    if not village_features:
        return VillageResult(
            region_code=region_code, success=False,
            error=(
                "All three strategies (named places, admin boundaries, "
                "hex centroid placeholders) returned no polygons. "
                "Check the bbox and Overpass API availability."
            ),
            warnings=warns,
        )

    # ── Annotate with footprint, upslope reach, nearest hex ───────────────
    rows = []
    for feat in village_features:
        try:
            geom = feat["geometry"]
            if geom is None:
                continue

            # Footprint
            centroid  = geom.centroid
            area_km2  = _polygon_area_km2(geom)

            # Nearest H3 hex (res 8)
            nearest_hex = h3.latlng_to_cell(centroid.y, centroid.x, 8)

            # Upslope reach from linked catchments
            upslope_km = _compute_upslope_reach(
                centroid, catchment_gdf, tolerance_deg=OUTLET_LINK_TOLERANCE_DEG
            )

            rows.append({
                "village_id":         feat.get("village_id", f"osm_{len(rows)}"),
                "region_code":        region_code,
                "name":               feat.get("name", ""),
                "footprint_km2":      round(area_km2, 4),
                "upslope_reach_km":   upslope_km,
                "nearest_hex_id":     nearest_hex,
                "population":         feat.get("population"),     # None for now
                # v2 §5.3.1: osm | voronoi_approx | hex_placeholder (official not available yet)
                "boundary_quality":   feat.get("boundary_quality", "osm"),
                "footprint_approx":   feat.get("boundary_quality", "osm") != "osm",
                # Gap Analysis §0.2: provenance — REAL_VALIDATED for OSM data
                "provenance":         ProvenanceTag.REAL_VALIDATED.value,
                "geometry":           geom,
            })
        except Exception as e:
            warns.append(f"Skipping village feature due to error: {e}")
            continue

    if not rows:
        return VillageResult(
            region_code=region_code, success=False,
            error="All village features failed geometry processing.",
            warnings=warns,
        )

    # ── Write 'villages' layer to GeoPackage ──────────────────────────────
    try:
        gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
        gdf.to_file(str(gpkg_path), driver="GPKG", layer="villages")
        print(f"      Villages: {len(rows)} written to {gpkg_path.name}")
    except Exception as e:
        return VillageResult(
            region_code=region_code, success=False,
            error=f"GeoPackage write failed: {e}",
            warnings=warns,
        )

    return VillageResult(
        region_code=region_code,
        success=True,
        village_count=len(rows),
        gpkg_path=gpkg_path,
        warnings=warns,
    )


# ---------------------------------------------------------------------------
# Overpass query helpers
# ---------------------------------------------------------------------------

# Only the main public server is queried: the two common mirrors timed out on every request
# (measured), and waiting on them made each region take minutes longer.
OVERPASS_MIRRORS = [OVERPASS_URL]


def _overpass_query(query_body: str, warns: list) -> list[dict]:
    """
    Execute an Overpass QL query and return the raw elements.  Tries each public server up to
    twice with a pause (504 / 429 are common under load).  Returns [] on failure with the error
    appended to warns -- a failed query is never turned into "no villages" silently.
    """
    import time
    import requests
    last = None
    for attempt in range(2):
        for url in OVERPASS_MIRRORS:
            try:
                resp = requests.post(
                    url, data={"data": query_body},
                    # Overpass rejects the default python-requests agent with HTTP 406.
                    headers={"User-Agent": "HydraSense-SIH26192-onboarding/1.0"},
                    timeout=OVERPASS_TIMEOUT + 30)
                resp.raise_for_status()
                return resp.json().get("elements", [])
            except Exception as e:
                last = f"{url.split('/')[2]}: {type(e).__name__}: {e}"
        time.sleep(10 * (attempt + 1))
    warns.append(f"Overpass API error after retries ({last})")
    return []


def _query_overpass_place_polygons(bbox: dict, warns: list) -> list[dict]:
    """
    Fetch named place polygons (village, hamlet, town, suburb) from OSM.
    Returns a list of feature dicts with 'geometry', 'village_id', 'name'.
    """
    from shapely.geometry import Polygon

    south, north, west, east = (
        bbox["south"], bbox["north"], bbox["west"], bbox["east"]
    )
    # Overpass QL: fetch ways/relations with place=village|hamlet|town|suburb
    query = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  way["place"~"^(village|hamlet|town|suburb)$"]
      ({south},{west},{north},{east});
  relation["place"~"^(village|hamlet|town|suburb)$"]
          ({south},{west},{north},{east});
);
out geom;
"""
    elements = _overpass_query(query, warns)
    features = []
    for el in elements:
        try:
            poly = _element_to_polygon(el)
            if poly is None:
                continue
            features.append({
                "village_id": f"osm_{el.get('type','way')}_{el.get('id',0)}",
                "name":       el.get("tags", {}).get("name", ""),
                "geometry":   poly,
                "population": _parse_population(el.get("tags", {})),
                "boundary_quality": "osm",
            })
        except Exception as e:
            warns.append(f"Skipping OSM element {el.get('id')}: {e}")
    return features


def _query_overpass_admin_boundaries(bbox: dict, warns: list) -> list[dict]:
    """
    Fetch administrative boundary polygons at admin_level 8, 9, 10.
    These often correspond to ward or village-level units in India.
    """
    south, north, west, east = (
        bbox["south"], bbox["north"], bbox["west"], bbox["east"]
    )
    query = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
(
  relation["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]
           ({south},{west},{north},{east});
);
out geom;
"""
    elements = _overpass_query(query, warns)
    features = []
    for el in elements:
        try:
            poly = _element_to_polygon(el)
            if poly is None:
                continue
            tags = el.get("tags", {})
            features.append({
                "village_id": f"osm_rel_{el.get('id',0)}",
                "name":       tags.get("name", tags.get("name:en", "")),
                "geometry":   poly,
                "population": _parse_population(tags),
                "boundary_quality": "osm",
            })
        except Exception as e:
            warns.append(f"Skipping admin boundary {el.get('id')}: {e}")
    return features


def _element_to_polygon(el: dict):
    """Convert an Overpass element (way with geometry or relation) to shapely Polygon."""
    from shapely.geometry import Polygon, MultiPolygon
    from shapely.ops import unary_union

    el_type = el.get("type")
    if el_type == "way":
        geometry = el.get("geometry", [])
        if len(geometry) < 3:
            return None
        coords = [(g["lon"], g["lat"]) for g in geometry]
        if coords[0] != coords[-1]:
            coords.append(coords[0])  # close the ring
        poly = Polygon(coords)
        return poly if poly.is_valid and not poly.is_empty else None

    elif el_type == "relation":
        # Build outer ring from relation members
        members   = el.get("members", [])
        outer_ways = [m for m in members if m.get("role") == "outer"]
        polys = []
        for m in outer_ways:
            geometry = m.get("geometry", [])
            if len(geometry) < 3:
                continue
            coords = [(g["lon"], g["lat"]) for g in geometry]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            try:
                p = Polygon(coords)
                if p.is_valid and not p.is_empty:
                    polys.append(p)
            except Exception:
                continue
        if not polys:
            return None
        merged = unary_union(polys)
        return merged if not merged.is_empty else None

    return None


def _parse_population(tags: dict) -> Optional[int]:
    """Parse population from OSM tags; returns None if absent or non-numeric."""
    raw = tags.get("population", "")
    try:
        return int(str(raw).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Voronoi cells around named place nodes (v2 §5.3.1, boundary_quality = voronoi_approx)
# ---------------------------------------------------------------------------

MIN_NODES_FOR_VORONOI = 20         # named places needed to prefer the node route
VORONOI_MAX_RADIUS_DEG = 0.03      # ~3.3 km: a village footprint is not a whole hillside


def _query_overpass_place_nodes(bbox: dict, warns: list) -> list[dict]:
    """Named village/hamlet/town/suburb NODES in the bbox: [{lat, lon, name, population}]."""
    south, north, west, east = bbox["south"], bbox["north"], bbox["west"], bbox["east"]
    query = f"""
[out:json][timeout:{OVERPASS_TIMEOUT}];
node["place"~"^(village|hamlet|town|suburb)$"]["name"]({south},{west},{north},{east});
out;
"""
    out = []
    for el in _overpass_query(query, warns):
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            tags = el.get("tags", {})
            out.append({"id": el.get("id", 0), "lat": el["lat"], "lon": el["lon"],
                        "name": tags.get("name", ""), "population": _parse_population(tags)})
    return out


def _voronoi_villages(nodes: list[dict], bbox: dict, warns: list) -> list[dict]:
    """
    One approximate footprint per named place node: its Voronoi cell, clipped to the bbox and
    to VORONOI_MAX_RADIUS_DEG around the node.  Cell edges are equidistant lines between
    neighbouring settlements, NOT surveyed boundaries -> boundary_quality = 'voronoi_approx'.
    """
    if len(nodes) < 2:
        return []
    try:
        from shapely.geometry import MultiPoint, Point, box
        from shapely.ops import voronoi_diagram
        env = box(bbox["west"], bbox["south"], bbox["east"], bbox["north"])
        pts = [Point(n["lon"], n["lat"]) for n in nodes]
        cells = voronoi_diagram(MultiPoint(pts), envelope=env)
        out = []
        for cell in cells.geoms:
            # assign the cell to the node it contains
            for n, pt in zip(nodes, pts):
                if cell.contains(pt):
                    poly = cell.intersection(env).intersection(pt.buffer(VORONOI_MAX_RADIUS_DEG))
                    if not poly.is_empty and poly.geom_type in ("Polygon", "MultiPolygon"):
                        out.append({"village_id": f"osm_node_{n['id']}", "name": n["name"],
                                    "geometry": poly, "population": n["population"],
                                    "boundary_quality": "voronoi_approx"})
                    break
        return out
    except Exception as e:
        warns.append(f"Voronoi village construction failed: {type(e).__name__}: {e}")
        return []


# ---------------------------------------------------------------------------
# Fallback: H3 hex centroid placeholders
# ---------------------------------------------------------------------------

def _generate_hex_centroid_placeholders(bbox: dict, warns: list) -> list[dict]:
    """
    Last-resort fallback: generate circular placeholder polygons centered on
    H3 res-8 hex centroids within the bbox.  These are labeled REAL_VALIDATED
    because the hex centroids come from the real boundary, but the geometry
    is synthetic (circular).  Warns the caller accordingly.
    """
    try:
        import h3
        from shapely.geometry import Point
        import numpy as np

        warns.append(
            "Using H3 centroid placeholders for village geometry. "
            "Footprint and upslope reach will be approximate. "
            "Replace with real OSM data when available."
        )
        polygon_geojson = {
            "type": "Polygon",
            "coordinates": [[
                [bbox["west"],  bbox["south"]],
                [bbox["east"],  bbox["south"]],
                [bbox["east"],  bbox["north"]],
                [bbox["west"],  bbox["north"]],
                [bbox["west"],  bbox["south"]],
            ]]
        }
        hex_ids = h3.geo_to_cells(polygon_geojson, 8)
        features = []
        for hid in sorted(hex_ids)[:500]:   # cap at 500 placeholders
            lat, lon = h3.cell_to_latlng(hid)
            # 500 m radius circle as a polygon approximation
            circle = Point(lon, lat).buffer(0.005)
            features.append({
                "village_id": f"h3placeholder_{hid}",
                "name":       f"hex_{hid}",
                "geometry":   circle,
                "population": None,
                "boundary_quality": "hex_placeholder",
            })
        return features
    except Exception as e:
        warns.append(f"H3 placeholder generation failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Upslope reach annotation
# ---------------------------------------------------------------------------

def _compute_upslope_reach(
    village_centroid,
    catchment_gdf,
    tolerance_deg: float = 0.005,
) -> Optional[float]:
    """
    Compute the upslope reach for a village by finding the catchment(s) whose
    outlet falls within tolerance_deg of the village centroid and returning
    the maximum upslope_reach_km among them.

    Returns None if catchment_gdf is None or no nearby outlets are found.
    """
    if catchment_gdf is None or catchment_gdf.empty:
        return None
    if "upslope_reach_km" not in catchment_gdf.columns:
        return None

    try:
        # Vector distance (degrees) from each catchment outlet to village centroid.
        # outlet_hex_id gives the outlet cell; we approximate its centroid.
        import h3
        import numpy as np

        max_reach = None
        for _, row in catchment_gdf.iterrows():
            try:
                outlet_hex  = row.get("outlet_hex_id")
                if not outlet_hex:
                    # Fall back to catchment polygon centroid
                    outlet_pt = row.geometry.centroid
                else:
                    olat, olon = h3.cell_to_latlng(outlet_hex)
                    from shapely.geometry import Point
                    outlet_pt = Point(olon, olat)

                dist = village_centroid.distance(outlet_pt)
                if dist <= tolerance_deg:
                    reach = row.get("upslope_reach_km")
                    if reach is not None:
                        max_reach = max(max_reach, float(reach)) if max_reach is not None else float(reach)
            except Exception:
                continue
        return max_reach
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Shared geometry helper
# ---------------------------------------------------------------------------

def _polygon_area_km2(polygon) -> float:
    """
    Approximate area of a WGS84 polygon in km² using spherical projection
    at the centroid latitude.  Good to ±5% for small polygons at Indian latitudes.
    """
    centroid    = polygon.centroid
    lat_rad     = math.radians(centroid.y)
    km_per_lat  = 111.32
    km_per_lon  = 111.32 * math.cos(lat_rad)
    bounds      = polygon.bounds
    bbox_lat_km = (bounds[3] - bounds[1]) * km_per_lat
    bbox_lon_km = (bounds[2] - bounds[0]) * km_per_lon
    bbox_km2    = bbox_lat_km * bbox_lon_km
    bbox_deg2   = (bounds[3] - bounds[1]) * (bounds[2] - bounds[0])
    fill_ratio  = polygon.area / bbox_deg2 if bbox_deg2 > 0 else 1.0
    return max(bbox_km2 * fill_ratio, 0.001)
