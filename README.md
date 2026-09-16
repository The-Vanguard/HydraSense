# HydraSense

**Flash Flood Prediction System for Hilly Regions using Multi-Source Data**

SIH Problem Statement ID: SIH26192

HydraSense is a last-mile downscaling and early-warning layer built on top of India's existing
operational flood and landslide guidance systems (SAsiaFFGS, GSI RLFS). It resolves coarse
district-scale forecasts to village/ward resolution using H3 hexagonal grids, integrates
multi-source sensor and terrain data, and auto-issues CAP-compliant Sachet alerts the moment a
hex crosses a risk threshold — removing the manual forecaster-relay step.

**Pilot region:** Wayanad district, Kerala — Mundakkai, Chooralmala, Attamala, Punjirimattom.

---

## Architecture

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 18, Vite, Leaflet | Interactive risk map, hex drill-down, live alert feed |
| Backend | FastAPI, Uvicorn, SQLite | REST API, risk engine, CAP alert pipeline |
| ML | XGBoost, TabPFN, Chronos-Bolt | Fusion risk model, multi-region inference, time-series forecasting |
| IoT | Python MQTT simulator | Sensor ingestion and state management |
| Data | H3 hexes (res 8-9), DEM, soil, rainfall | Multi-source feature store |

---

## Repository Structure

```
backend/            FastAPI application — API routers, risk engine, alert pipeline, database layer
  routers/          Individual route modules (risk, events, simulate, alerts)
  main.py           Application entry point
  risk_engine.py    Core hazard scoring and fusion logic
  lead_time.py      Lead-time and factor-of-safety computation
  seed.py           Wayanad pilot hex seeding
  seed_multiregion.py  Multi-region hex seeding

frontend/           React + Leaflet dashboard
  src/
    App.jsx         Root component and state management
    components/     UI panels (HexMap, ManualScenarioPanel, HistoricalEventPanel, AlertFeed, ...)
    utils/          Client-side geospatial inference (pinSimulation.js)
    api/            Backend API client

ml/                 Machine learning pipeline
  features/         Feature engineering and event-centered sampling
  models/           XGBoost fusion model training
  validation/       Leave-one-event-out (LOEO) evaluation harness

iot/                IoT sensor simulation
  simulator.py      MQTT-based sensor state generator

data/               Data store (large generated files are gitignored)
  multiregion/      Sampling, model-ready CSVs, inference scripts
  terrain/          DEM tiles and slope/aspect derivatives
  soil/             Soil moisture and texture data
  validation/       LOEO results and summary statistics
  weather/          Cached weather snapshots

docs/               Project documentation
  SRS.md            Full Software Requirements and Reference Specification (v2.0 final)
  data_limitations.md  Known data gaps and mitigation notes

scripts/            Standalone utility scripts
SRS.md              Canonical SRS (root copy — authoritative)
CLAUDE.md           Hard constraints for all coding sessions
```

---

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
python seed.py                  # seed Wayanad pilot hexes
python seed_multiregion.py      # seed multi-region hex data
uvicorn main:app --reload
```

API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard runs at `http://localhost:5173`.

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENTOPO_API_KEY` | For DEM ingest | OpenTopography API key (`data/scripts/ingest_dem.py`) |
| `NTFY_TOPIC` | Optional | ntfy.sh topic for push alert delivery |

### Regenerating Large Data Files

The following files are excluded from version control due to size and must be regenerated locally:

```bash
# Multi-region weather and soil data
python data/multiregion/scripts/ingest_rainfall_historical_multiregion.py
python data/multiregion/scripts/ingest_soil_multiregion.py

# ML inference
python data/multiregion/scripts/prepare_tabpfn_input.py
python data/multiregion/scripts/run_tabpfn_inference.py
python data/multiregion/scripts/run_chronos_inference.py
```

---

## Key API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/risk/map` | All hex risk scores for map rendering |
| GET | `/risk/{hex_id}` | Full feature breakdown for a single hex |
| GET | `/events/` | Historical flood events with metadata |
| POST | `/simulate/pin` | Client-submitted coordinate risk inference |
| GET | `/alerts/cap` | Latest CAP-compliant alert feed |

---

## Model Overview

The fusion model combines four input streams:

1. **Rainfall** — 24h cumulative and antecedent (3-day, 7-day) from IMD/Open-Meteo
2. **Soil moisture** — satellite-derived volumetric water content (ERA5-Land / SMAP proxy)
3. **Terrain** — slope angle, TWI, curvature from SRTM 30m DEM
4. **Vegetation / land cover** — NDVI-derived surface roughness

An XGBoost classifier produces a continuous risk score [0, 1]. A physically-derived
Factor-of-Safety (Fs) model runs in parallel for slope-failure probability, carrying an
explicit uncertainty band based on soil cohesion variability.

Lead time is computed as the estimated hours before the hex is expected to cross the critical
threshold given the current rainfall rate trajectory.

**Validation:** Leave-one-event-out (LOEO) cross-validation across sourced historical flood
events. Results in `data/validation/loeo_results.json`.

---

## Multi-Region Coverage

The system has been validated across ten hilly districts in India:

| Region | State |
|---|---|
| Wayanad | Kerala |
| Idukki | Kerala |
| Nilgiris | Tamil Nadu |
| Chamoli | Uttarakhand |
| Rudraprayag | Uttarakhand |
| Kullu | Himachal Pradesh |
| Sikkim Mangan | Sikkim |
| Darjeeling / Kalimpong | West Bengal |
| Dhemaji | Assam |
| Ribhoi | Meghalaya |

---

## Key Documents

- [`SRS.md`](./SRS.md) — Single source of truth for all requirements, schema, API contracts,
  data definitions, and the full phase-by-phase build plan. Read this before touching any
  component.
- [`CLAUDE.md`](./CLAUDE.md) — Hard constraints enforced in every coding session (map library,
  data fabrication rules, alert pipeline rules).
- [`docs/data_limitations.md`](./docs/data_limitations.md) — Known data gaps and mitigation
  approaches for each input stream.

---

## Development Notes

- All map rendering uses **Leaflet only**. Mapbox and other tile providers are not permitted.
- The pilot scope is Wayanad H3 resolution 8-9 hexes. The backend API serves real model output
  for these hexes; out-of-region coordinates use the client-side inference layer.
- Alert delivery is wired through ntfy.sh (CAP-compliant payload). The `data/alerts/` directory
  is gitignored as it is regenerated on each run.
- SQLite is used for the pilot database. Schema is defined in `backend/models.py` and
  `backend/database.py`.

---

## Team

Project developed by Team Vanguard for Smart India Hackathon 2026.
GitHub organisation: [The-Vanguard](https://github.com/The-Vanguard)