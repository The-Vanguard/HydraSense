# Data Ingestion Scripts (Phase 1)

Implements SRS.md Section 8 — all data sources for the Wayanad pilot cluster.
Owner: Dev A.

## Scripts

| Script | Source | Key Required? | Output |
|---|---|---|---|
| `ingest_rainfall.py` | Open-Meteo API | No | `data/weather/rainfall_current.json`, `data/weather/rainfall_forecast.json` |
| `ingest_dem.py` | OpenTopography (SRTM 30m) | Yes — env var `OPENTOPO_API_KEY` | `data/terrain/dem_wayanad.tif` |
| `ingest_soil.py` | NASA POWER (GWETROOT) | No | `data/soil/soil_moisture.json` |
| `ingest_landcover.py` | ESA WorldCover S3 (public) | No | `data/landcover/landcover_wayanad.tif`, `data/landcover/ndvi_wayanad.tif` |

## Prerequisites

```bash
pip install httpx

# For ingest_dem.py: OpenTopography free API key
# Sign up at https://opentopography.org/ (instant, no approval wait)
# Then set env var:
$env:OPENTOPO_API_KEY = "your_key_here"        # PowerShell
export OPENTOPO_API_KEY="your_key_here"         # bash

# For ingest_landcover.py: AWS CLI + GDAL
# AWS CLI: https://aws.amazon.com/cli/
# GDAL: conda install -c conda-forge gdal   OR   apt install gdal-bin
```

## Run order

```bash
python data/scripts/ingest_rainfall.py
python data/scripts/ingest_dem.py          # needs OPENTOPO_API_KEY set
python data/scripts/ingest_soil.py
python data/scripts/ingest_landcover.py    # needs aws CLI + gdal_translate
```

All scripts run standalone with no interactive prompts.
All scripts **fail loudly** (exit 1 + error message) on API failure — per CLAUDE.md,
no script silently substitutes fake data.

## Hard constraints (CLAUDE.md)

- NASA SMAP is **never** used — only NASA POWER GWETROOT.
- `soil_saturation_ratio = GWETROOT` directly (no formula derivation).
- NASA POWER has ~50km native resolution. Label as **"soil saturation proxy"** everywhere.
- pysheds is the terrain library for Phase 3 — not used in these ingestion scripts.

## Output notes

- `rainfall_forecast.json` is required by Phase 9 (lead-time computation per SRS.md §12).
- Large GeoTIFFs are gitignored (`data/.gitignore`). Re-run scripts to regenerate.
- `data/weather/cached_demo_snapshot.json` is NOT produced by these scripts —
  it is pre-fetched manually before demo day (Phase 9, SRS.md Section 13).
