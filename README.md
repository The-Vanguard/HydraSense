# HydraSense

A last-mile downscaling layer for India's existing flash-flood and landslide guidance systems.

> **Pilot region:** Wayanad district, Kerala — Mundakkai, Chooralmala, Attamala, Punjirimattom villages.

## Project Structure

```
/backend    FastAPI + PostGIS — all API endpoints and database
/frontend   React + Leaflet dashboard
/ml         Feature engineering, FS model, XGBoost training, LOEO harness
/iot        MQTT IoT simulator
/data       Raw and processed data files (large files gitignored)
/docs       SRS.md and project documentation
```

## Key Documents

- `/docs/SRS.md` — Single source of truth for all requirements, schema, API contracts, and build phases.
- `CLAUDE.md` — Hard constraints for all coding sessions. Read before writing any code.

## Quick Start

See each component's `requirements.txt` or `package.json` for dependencies.
Set `OPENTOPO_API_KEY` environment variable before running `data/scripts/ingest_dem.py`.