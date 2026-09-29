"""
backend/onboarding/pipeline.py
Autonomous Region Onboarding Pipeline — orchestrator (Final.md §6, §16.3).

This is the single entry point that runs identically for ANY hilly region in India.
No region is special-cased. Wayanad is just one entry in ALL_REGIONS below.

Steps per Final.md §6:
  1. Boundary resolution (boundary.py)
  2. DEM fetch (dem.py)
  3. Terrain derivatives (terrain.py)
  4. ESA WorldCover land-cover fetch  [inline via requests + rasterio]
  5. SoilGrids geotechnical params (soilgrids.py)
  6. H3 grid generation (h3_grid.py)
  7. Historical context check → has_local_calibration (history_check.py)
  8. GeoPackage write (geopackage.py)
  9. Seed hydrasense.db hexes table from GeoPackage

ALL_REGIONS: the complete list of 10 hilly regions HydraSense supports.
  Each entry drives the SAME pipeline — no per-region branches anywhere.

Usage:
  # Onboard a single region from its place name:
  python -m backend.onboarding.pipeline --region wayanad

  # Onboard all 10 regions:
  python -m backend.onboarding.pipeline --all

  # Called by POST /region/resolve for live onboarding:
  from backend.onboarding.pipeline import run_pipeline
  result = run_pipeline("Rudraprayag Uttarakhand")
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.onboarding.boundary     import resolve_boundary, BoundaryResult
from backend.onboarding.dem          import fetch_dem_for_region
from backend.onboarding.terrain      import compute_terrain_features
from backend.onboarding.soilgrids    import derive_soil_params
from backend.onboarding.h3_grid      import build_h3_grid
from backend.onboarding.history_check import check_local_calibration
from backend.onboarding.geopackage   import save_region_gpkg, region_is_onboarded
# Gap Analysis Phase 0 — provenance policy
from backend.provenance import ProvenanceTag
# Gap Analysis Phase 1 — catchments and villages
from backend.onboarding.catchments   import delineate_catchments
from backend.onboarding.villages     import fetch_village_polygons

# ---------------------------------------------------------------------------
# ALL_REGIONS — the authoritative list of supported regions
# Every entry runs through the EXACT SAME pipeline. No per-region code.
# Wayanad is entry #0, not a special case.
# ---------------------------------------------------------------------------
ALL_REGIONS: list[dict] = [
    # ── Western Ghats ────────────────────────────────────────────────────
    {
        "query":        "Wayanad Kerala India",
        "region_code":  "wayanad-kl",
        "label":        "Wayanad, Kerala (Western Ghats)",
        "zone":         "western_ghats",
    },
    {
        "query":        "Idukki Kerala India",
        "region_code":  "idukki-kl",
        "label":        "Idukki, Kerala (Western Ghats)",
        "zone":         "western_ghats",
    },
    {
        "query":        "Nilgiris Tamil Nadu India",
        "region_code":  "nilgiris-tn",
        "label":        "The Nilgiris, Tamil Nadu (Western Ghats)",
        "zone":         "western_ghats",
    },
    # ── Himalayan ────────────────────────────────────────────────────────
    {
        "query":        "Rudraprayag Uttarakhand India",
        "region_code":  "rudraprayag-uk",
        "label":        "Rudraprayag, Uttarakhand (Himalayan)",
        "zone":         "himalayan",
    },
    {
        "query":        "Chamoli Uttarakhand India",
        "region_code":  "chamoli-uk",
        "label":        "Chamoli, Uttarakhand (Himalayan)",
        "zone":         "himalayan",
    },
    {
        "query":        "Kullu Himachal Pradesh India",
        "region_code":  "kullu-hp",
        "label":        "Kullu, Himachal Pradesh (Himalayan)",
        "zone":         "himalayan",
    },
    {
        "query":        "Mangan Sikkim India",
        "region_code":  "mangan-sk",
        "label":        "Mangan, Sikkim (Himalayan)",
        "zone":         "himalayan",
    },
    {
        "query":        "Darjeeling West Bengal India",
        "region_code":  "darjeeling-wb",
        "label":        "Darjeeling, West Bengal (Himalayan)",
        "zone":         "himalayan",
    },
    # ── Northeast ────────────────────────────────────────────────────────
    {
        "query":        "Ribhoi Meghalaya India",
        "region_code":  "ribhoi-ml",
        "label":        "Ribhoi (Nongpoh), Meghalaya (Northeast)",
        "zone":         "northeast",
    },
    {
        "query":        "Dhemaji Assam India",
        "region_code":  "dhemaji-as",
        "label":        "Dhemaji, Assam (Northeast / Flood-prone)",
        "zone":         "northeast",
    },
]

# Lookup by region_code for fast access
REGION_BY_CODE = {r["region_code"]: r for r in ALL_REGIONS}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    region_code:           str
    label:                 str
    success:               bool
    elapsed_s:             float = 0.0
    hex_count:             int = 0
    h3_resolution:         int = 8
    has_local_calibration: bool = False
    gpkg_path:             Optional[Path] = None
    boundary:              Optional[object] = None   # BoundaryResult
    soil_params:           Optional[object] = None   # SoilParams
    data_sources:          dict = field(default_factory=dict)
    error:                 Optional[str] = None
    warnings:              list[str] = field(default_factory=list)
    # Phase 1 additions (Gap Analysis §A3, A4)
    catchment_count:       int = 0    # number of micro-catchments delineated
    village_count:         int = 0    # number of village polygons fetched


# ---------------------------------------------------------------------------
# Single region pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    query: str,
    region_code: Optional[str] = None,
    force_rerun: bool = False,
) -> PipelineResult:
    """
    Run the full onboarding pipeline for one region.

    Args:
        query:       place name (e.g. "Wayanad Kerala India") or lat,lon string
        region_code: optional pre-known slug; if None, derived from geocoding
        force_rerun: if True, reprocess even if GeoPackage already exists

    Returns: PipelineResult
    """
    t0    = time.perf_counter()
    warns = []

    print(f"\n{'='*60}")
    print(f"  Onboarding: {query}")
    print(f"{'='*60}")

    # ── Step 1: Boundary resolution ──────────────────────────────────────
    print("  [1/8] Resolving boundary...")
    boundary = resolve_boundary(query)
    if not boundary.bbox:
        return PipelineResult(
            region_code=region_code or "unknown", label=query, success=False,
            elapsed_s=time.perf_counter() - t0,
            error=f"Boundary resolution failed for '{query}' — geocoding returned no bbox",
        )
    if region_code:
        boundary.region_code = region_code
    rc = boundary.region_code
    print(f"      {boundary.display_name[:70]}")
    print(f"      BBox: S={boundary.bbox['south']:.4f} N={boundary.bbox['north']:.4f} "
          f"W={boundary.bbox['west']:.4f} E={boundary.bbox['east']:.4f}")
    print(f"      region_code: {rc}")
    print(f"      Admin: {' > '.join(boundary.admin_breadcrumb)}")

    # ── Step 2: DEM fetch ─────────────────────────────────────────────────
    print("  [2/10] Fetching DEM...")
    dem_result = fetch_dem_for_region(rc, boundary.bbox)
    data_sources = {"terrain": "live" if dem_result.source == "live" else
                                "cached" if dem_result.source == "cached" else "unavailable"}
    # Gap Analysis §0.2 Phase 0: stamp hex-grid provenance in data_sources
    data_sources["hex_grid_provenance"] = (
        ProvenanceTag.REAL_VALIDATED.value
        if dem_result.success
        else ProvenanceTag.SIMULATED.value
    )
    if not dem_result.success:
        warns.append(f"DEM unavailable: {dem_result.error}")
        print(f"      WARNING: DEM unavailable — {dem_result.error[:80] if dem_result.error else ''}")

    # ── Step 3: Terrain derivatives ───────────────────────────────────────
    print("  [3/10] Computing terrain derivatives...")
    terrain_result = None
    if dem_result.success and dem_result.dem_path:
        terrain_result = compute_terrain_features(rc, dem_result.dem_path)
        if not terrain_result.success:
            warns.append(f"Terrain computation failed: {terrain_result.error}")
    else:
        warns.append("Terrain derivatives skipped — no DEM available")

    # ── Step 4: ESA WorldCover land cover (inline, use cached if available) ─
    print("  [4/10] Loading land cover...")
    lulc_path = ROOT / "data" / "landcover" / rc / f"worldcover_{rc}.tif"
    if not lulc_path.exists():
        # Try legacy Wayanad path for backward-compat
        legacy = ROOT / "data" / "landcover" / "landcover_wayanad.tif"
        if legacy.exists() and "wayanad" in rc:
            lulc_path = legacy
    lulc_raster = lulc_transform = None
    if lulc_path.exists():
        try:
            import rasterio
            with rasterio.open(lulc_path) as src:
                import numpy as np
                lulc_raster    = src.read(1).astype("int16")
                lulc_transform = src.transform
            data_sources["land_cover"] = "cached"
            print(f"      Land cover: {lulc_path.name}")
        except Exception as e:
            warns.append(f"Land cover read failed: {e}")
    else:
        data_sources["land_cover"] = "unavailable"
        warns.append("Land cover not found — land_use_class will be None for this region")
        print("      WARNING: land cover not found — run ESA WorldCover fetch for this region")

    # ── Step 5: SoilGrids geotechnical params ────────────────────────────
    print("  [5/10] Deriving soil/geotechnical parameters...")
    # Calibration flag needed for band widening — do a quick pre-check
    pre_cal = check_local_calibration(rc, boundary.bbox, boundary.district, boundary.state)
    soil_params = derive_soil_params(rc, has_local_calibration=pre_cal.has_local_calibration)
    data_sources["soil"] = soil_params.data_source
    print(f"      Soil source: {soil_params.data_source}  "
          f"coverage: {soil_params.coverage_pct:.0f}%  "
          f"c'={soil_params.c_prime_kpa:.1f}kPa  phi={soil_params.phi_deg:.1f}deg  "
          f"gamma={soil_params.gamma_kn_m3:.1f}kN/m3")
    if not soil_params.success:
        warns.append(f"Soil params fallback: {soil_params.error}")

    # ── Step 6: H3 grid generation ────────────────────────────────────────
    print("  [6/10] Generating H3 grid and sampling features...")
    grid_result = build_h3_grid(
        region_code=rc,
        bbox=boundary.bbox,
        terrain_result=terrain_result,
        lulc_raster=lulc_raster,
        lulc_transform=lulc_transform,
        gsi_class_by_hex=None,   # populated in Step 7
    )

    # ── Step 7: Historical calibration check ──────────────────────────────
    print("  [7/10] Checking local calibration...")
    cal_result = check_local_calibration(rc, boundary.bbox, boundary.district, boundary.state)
    print(f"      has_local_calibration = {cal_result.has_local_calibration}")
    print(f"      {cal_result.confidence_note[:80]}")

    # Back-fill has_local_calibration into every hex feature row
    for hex_id in grid_result.hex_ids:
        grid_result.hex_features[hex_id]["has_local_calibration"] = cal_result.has_local_calibration

    # ── Step 8: Write GeoPackage ──────────────────────────────────────────
    print("  [8/10] Writing GeoPackage...")
    gpkg_path = save_region_gpkg(rc, grid_result, boundary)

    # ── Seed hydrasense.db hexes table ────────────────────────────────────
    _seed_db_hexes(rc, grid_result, soil_params, cal_result)

    # ── Step 9: Micro-catchment delineation (Gap Analysis §A3) ───────────
    print("  [9/10] Delineating micro-catchments...")
    catchment_result = delineate_catchments(
        region_code=rc,
        dem_path=dem_result.dem_path if dem_result.success else None,
        gpkg_path=gpkg_path,
        bbox=boundary.bbox,
    )
    if catchment_result.success:
        print(f"      Catchments: {catchment_result.catchment_count} delineated")
    else:
        warns.append(f"Catchment delineation skipped: {catchment_result.error}")
        print(f"      WARNING: {catchment_result.error[:80] if catchment_result.error else ''}")

    # ── Step 10: Village polygons with footprint and upslope reach (Gap Analysis §A4) ─
    print("  [10/10] Fetching village polygons and computing upslope reach...")
    village_result = fetch_village_polygons(
        region_code=rc,
        bbox=boundary.bbox,
        gpkg_path=gpkg_path,
        catchment_result=catchment_result,
    )
    if village_result.success:
        print(f"      Villages: {village_result.village_count} polygons written")
    else:
        warns.append(f"Village polygons skipped: {village_result.error}")
        print(f"      WARNING: {village_result.error[:80] if village_result.error else ''}")

    elapsed = time.perf_counter() - t0
    print(f"\n  Done: {rc} — {grid_result.hex_count} hexes, {elapsed:.1f}s")
    if warns:
        for w in warns:
            print(f"  WARN: {w}")

    return PipelineResult(
        region_code=rc, label=boundary.display_name,
        success=True, elapsed_s=elapsed,
        hex_count=grid_result.hex_count, h3_resolution=grid_result.resolution,
        has_local_calibration=cal_result.has_local_calibration,
        gpkg_path=gpkg_path, boundary=boundary, soil_params=soil_params,
        data_sources=data_sources, warnings=warns,
        catchment_count=catchment_result.catchment_count if catchment_result.success else 0,
        village_count=village_result.village_count if village_result.success else 0,
    )


# ---------------------------------------------------------------------------
# DB seeding
# ---------------------------------------------------------------------------

def _seed_db_hexes(
    region_code: str,
    grid_result,
    soil_params,
    cal_result,
) -> None:
    """
    Insert/update hexes into hydrasense.db from the onboarding result.
    This replaces the per-region seed.py / seed_multiregion.py approach.
    """
    import sqlite3, json
    import h3

    db_path = ROOT / "data" / "hydrasense.db"
    if not db_path.exists():
        print("      DB: hydrasense.db not found — skipping DB seed")
        return

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        inserted = updated = 0
        for hex_id in grid_result.hex_ids:
            feats = grid_result.hex_features.get(hex_id, {})
            lat, lon = h3.cell_to_latlng(hex_id)

            # Build static_features JSON (matches existing schema)
            static_feats = {k: v for k, v in feats.items()
                            if k not in ("has_local_calibration",)}
            static_feats["has_local_calibration"] = feats.get("has_local_calibration", False)

            # Add soil params to static features
            static_feats["soil_c_prime_kpa"]  = soil_params.c_prime_kpa
            static_feats["soil_phi_deg"]       = soil_params.phi_deg
            static_feats["soil_z_m"]           = soil_params.z_m
            static_feats["soil_gamma_kn_m3"]   = soil_params.gamma_kn_m3
            static_feats["soil_data_source"]   = soil_params.data_source

            # Upsert into hexes table.  Real schema: hex_id, geom (GeoJSON polygon, [lng,lat]),
            # static_features, region_code, resolution  (see backend/database.py, backend/seed.py).
            ring = [[lng, lat_] for lat_, lng in h3.cell_to_boundary(hex_id)]
            ring.append(ring[0])
            geom = json.dumps({"type": "Polygon", "coordinates": [ring]})
            existed = cur.execute("SELECT 1 FROM hexes WHERE hex_id = ?", (hex_id,)).fetchone()
            cur.execute("""
                INSERT INTO hexes (hex_id, geom, static_features, region_code, resolution)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(hex_id) DO UPDATE SET
                    region_code      = excluded.region_code,
                    static_features  = excluded.static_features,
                    resolution       = excluded.resolution
            """, (hex_id, geom, json.dumps(static_feats), region_code, grid_result.resolution))
            if existed:
                updated += 1
            else:
                inserted += 1

        conn.commit()
        print(f"      DB: {inserted} inserted, {updated} updated in hexes table")
    except sqlite3.OperationalError as e:
        # Schema may not have region_code column yet — migrate gracefully
        print(f"      DB: schema mismatch, attempting migration — {e}")
        _migrate_db_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_db_schema(conn: "sqlite3.Connection") -> None:
    """Add region_code and resolution columns to hexes if missing."""
    cur = conn.cursor()
    for col, typ in [("region_code", "TEXT"), ("resolution", "INTEGER")]:
        try:
            cur.execute(f"ALTER TABLE hexes ADD COLUMN {col} {typ}")
        except Exception:
            pass   # column already exists


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="HydraSense Autonomous Region Onboarding Pipeline"
    )
    parser.add_argument("--region", help="region_code to onboard (e.g. wayanad-kl)")
    parser.add_argument("--all",    action="store_true", help="Onboard all 10 regions")
    parser.add_argument("--query",  help="Arbitrary place name to onboard")
    parser.add_argument("--force",  action="store_true", help="Re-run even if already onboarded")
    args = parser.parse_args()

    if args.all:
        targets = ALL_REGIONS
    elif args.region:
        match = REGION_BY_CODE.get(args.region)
        if not match:
            print(f"Unknown region_code: {args.region}")
            print(f"Available: {list(REGION_BY_CODE.keys())}")
            sys.exit(1)
        targets = [match]
    elif args.query:
        targets = [{"query": args.query, "region_code": None, "label": args.query, "zone": "unknown"}]
    else:
        parser.print_help()
        sys.exit(1)

    print(f"HydraSense Autonomous Region Onboarding Pipeline")
    print(f"Reference: HydraSense_Final.md §6 / §16.3")
    print(f"Regions to onboard: {len(targets)}\n")

    results = []
    for region_def in targets:
        result = run_pipeline(
            query=region_def["query"],
            region_code=region_def.get("region_code"),
            force_rerun=args.force,
        )
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("ONBOARDING SUMMARY")
    print(f"{'='*60}")
    ok  = [r for r in results if r.success]
    err = [r for r in results if not r.success]
    print(f"  Successful: {len(ok)}/{len(results)}")
    for r in ok:
        cal = "calibrated" if r.has_local_calibration else "uncalibrated"
        print(f"    {r.region_code:<20} {r.hex_count:>5} hexes  res={r.h3_resolution}  {cal}")
    if err:
        print(f"  Failed: {len(err)}")
        for r in err:
            print(f"    {r.region_code:<20} ERROR: {r.error}")
    print(f"{'='*60}")
    sys.exit(0 if not err else 1)


if __name__ == "__main__":
    main()
