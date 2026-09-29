# backend/onboarding/__init__.py
"""
backend/onboarding — Autonomous Region Onboarding Pipeline
(HydraSense_Final.md §6, §15.5, §16.3)

This package makes HydraSense region-agnostic.  It runs identically for
any hilly location in India — Wayanad, Rudraprayag, Chamoli, Ribhoi, or a
place typed in live during the demo — without any manual configuration.

Entry point:  pipeline.py  → run_pipeline(query) → OnboardingResult
FastAPI route: backend/routers/region.py  → POST /region/resolve

Modules:
  boundary.py     — Nominatim geocoding: place name → bbox + admin hierarchy
  dem.py          — OpenTopography GLO-30 DEM fetch → regional GeoTIFF
  terrain.py      — pysheds/rasterio: slope, aspect, TWI, TRI, HAND,
                    flow_accumulation, drainage_density, curve_number
  landcover.py    — ESA WorldCover 10m: per-hex LULC class + NDVI proxy
  soilgrids.py    — SoilGrids WCS bulk rasters → pedotransfer → c', phi', γ, z
  h3_grid.py      — H3 grid sized from resolved bbox (res 7/8/9, Final.md §14.7)
  history_check.py — GSI district overlap → has_local_calibration flag
  geopackage.py   — GeoPackage (.gpkg) read/write for per-region spatial data
  pipeline.py     — Orchestrates steps 1-8 of Final.md §6
"""

from .pipeline    import run_pipeline, PipelineResult, ALL_REGIONS, REGION_BY_CODE
from .catchments  import delineate_catchments, CatchmentResult
from .villages    import fetch_village_polygons, VillageResult
from backend.provenance import ProvenanceTag   # re-export for convenience
