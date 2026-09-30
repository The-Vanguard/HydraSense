# HydraSense

**Region-agnostic flash-flood and landslide decision support for hilly India**

SIH Problem Statement ID: **SIH26192** · Team Vanguard · Smart India Hackathon 2026

HydraSense is a last-mile downscaling layer on top of India's existing operational guidance (SAsiaFFGS, GSI).
It resolves a place name to terrain, soil, micro-catchments and village areas, scores risk per H3 hexagon,
rolls it up to villages, and drafts CAP 1.2 alerts held for two-person authorisation.
Confidence is reported per region and states how much local evidence backs it.

> **Read this first.** The architecture is complete and tested.
> See [Current status](#current-status-what-works-and-what-does-not) before quoting any number.

---

## What's new in v2

- **Disaster Intelligence & Warning Center** — redesigned dashboard with five tabs: Overview · GIS Risk Map · Alerts · Event Replay · Analytics
- **10 onboarded regions** across 6 states (Kerala, Tamil Nadu, Uttarakhand, Himachal Pradesh, Sikkim / West Bengal, Northeast)
- **Wayanad onboarded** as a full peer region (terrain + soil + villages + history)
- **Physics-first hazard index** as the live scoring engine (replaces ML stub)
- **LORO validation** across all 10 regions: 94.8 % aggregate detection rate, 0 % false-positive rate
- **Fixed overview map** — stays in view while side columns scroll; KPI cards count exactly what the map shows
- **Place-name labels** on hexagons instead of raw H3 IDs
- **Open-Meteo rate-limit fix** — single flight per cell with one retry; parallel scoring no longer trips the limit
- **Role switching** — Decision Authority and Response Unit views

---

## Architecture

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 18, Vite, deck.gl `H3HexagonLayer`, MapLibre GL (Leaflet fallback) | Risk map, village table, explainability, alert feed |
| Backend | FastAPI, Uvicorn, SQLite (`data/hydrasense.db`) + one GeoPackage per region | REST + WebSocket API, risk engine, CAP pipeline |
| Physics | Infinite-slope FS (Monte Carlo), SCS-CN runoff, I–D rainfall threshold, stream-blockage check | `backend/engines.py`, `backend/blockage.py`, `backend/physics_risk.py` |
| ML | XGBoost heads (landslide, flood) — **stubs; physics index used live** | `backend/ml.py` |
| IoT | Simulated MQTT publisher; QC, snapping, edge rule as pure logic | `iot/`, `backend/iot_qc.py` |
| Alerts | CAP 1.2 draft → two-person gate → WebSocket / ntfy.sh | `backend/alerts/` |
| Data | H3 res 8, SRTM DEM, SoilGrids, Open-Meteo, IMERG (optional) | Onboarding pipeline + feature store |

---

## Onboarded regions

| Code | Region | State |
|---|---|---|
| `wayanad-kl` | Wayanad | Kerala |
| `idukki-kl` | Idukki | Kerala |
| `nilgiris-tn` | The Nilgiris | Tamil Nadu |
| `rudraprayag-uk` | Rudraprayag | Uttarakhand |
| `chamoli-uk` | Chamoli | Uttarakhand |
| `kullu-hp` | Kullu | Himachal Pradesh |
| `mangan-sk` | Mangan | Sikkim |
| `darjeeling-wb` | Darjeeling | West Bengal |
| `ribhoi-ml` | Ri-Bhoi | Meghalaya |
| `dhemaji-as` | Dhemaji | Assam |

---

## Repository structure

```
backend/
  main.py                 FastAPI app (routers + WebSocket + scheduler lifespan)
  onboarding/             Region onboarding: boundary, DEM, terrain, catchments, villages,
                          SoilGrids, H3 grid, history check, GeoPackage writer, pipeline
  engines.py              E2 slope stability (FS Monte Carlo, I-D threshold), E3 runoff
  physics_risk.py         Physics-first hazard index (live scoring engine)
  blockage.py             E4 stream-blockage check (off without stage sensors)
  classifier.py           Rule-based trigger classifier
  village_rollup.py       Village value from hex risk (P90 + upslope reach), persistence
  confidence.py           Four-factor confidence with reasons
  iot_qc.py               Sensor QC, health, snapping, edge rule
  alerts/                 CAP generator, two-person gate, dedup, WebSocket, Cell Broadcast text
  routers/                risk, region, village, confidence, validation, events,
                          gate, ingest, simulate, shelters, evacuation
frontend/
  src/v2/                 HydraSense v2 dashboard (Dashboard, Shell, KPIs, MapCard, VillageCard, Sidebar)
  src/components/         Shared components (HexMap, AlertConsole, GatePanel, IncidentActionPlan, LoroPanel …)
  Dockerfile, nginx.conf  Container build
ml/
  features/, models/      Feature engineering and FS / fusion code (pre-v2)
  validation/             LOEO, LORO, spatial-block, calibration
  dataset/                Event geocoding, training-table build, baselines, IMERG comparison
iot/                      MQTT simulator
data/
  events/                 Historical events CSV, training tables (v0, v0p, v1, v1b)
  validation/             Stored validation results (calibration.json, loro_summary.json, …)
  multiregion/            Onboarding scripts, model-ready parquet (large files git-ignored)
scripts/                  Smoke tests, onboarding helpers, stage-0 API checks
tests/                    22-file pytest suite (~160 tests)
```

---

## Quick start

Python 3.12 recommended (geospatial wheels are available for it).

### Backend

```bash
pip install -r backend/requirements.txt -r ml/requirements.txt
uvicorn backend.main:app --reload        # API on http://localhost:8000  (docs at /docs)
```

### Frontend

```bash
cd frontend && npm install && npm run dev   # UI on http://localhost:5173
```

### Onboard a region

Needs network access. Writes `data/regions/<code>.gpkg` and seeds `data/hydrasense.db`.

```bash
python -m backend.onboarding.pipeline --region wayanad-kl --force
```

To onboard all pending regions at once:

```bash
python scripts/onboard_pending.py
```

### Seed demo risk scores

```bash
python backend/seed_demo_risk.py
```

### Docker

```bash
docker compose up          # backend :8000, frontend :5173
```

> Docker config is written (`docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`) but was not runtime-tested in the development environment.

### Tests

```bash
python -m pytest tests -q --ignore=tests/test_integration_final.py
```

(`tests/test_integration_final.py` calls `sys.exit()` on import; run it directly.)

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENTOPOGRAPHY_API_KEY` | For live DEM fetch | Used by `backend/onboarding/dem.py` (a cached DEM works without it) |
| `EARTHDATA_TOKEN` | Optional | NASA Earthdata token for IMERG satellite rain. Never commit; `.credentials/` is git-ignored |
| `NTFY_TOPIC` | Optional | ntfy.sh topic for push delivery |
| `HYDRASENSE_RISK_MODEL` | Optional | Set to `fusion` to use the ML stub instead of the physics-first index |

---

## Key API endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/region/resolve` | Resolve a place name to a region |
| GET | `/risk/map`, `/risk/{hex_id}` | Hex risk layer / single hex |
| GET | `/village/priority?region=` | Village roll-up, risk-ranked |
| GET | `/village/{id}/risk?region=` | Single village risk detail |
| GET | `/confidence/{hex_id}/factors` | Four-factor confidence with reasons and stated assumptions |
| GET | `/validation/loeo`, `/validation/loro` | Stored validation results |
| POST | `/alert/trigger` | Draft a CAP alert (held for gate) |
| POST | `/alert/gate/approve` | Second-person authorisation |
| GET | `/events/replay?region=` | Event replay feed |
| WS | `/ws/alerts` | Live alert WebSocket feed |

Full interactive docs: `http://localhost:8000/docs`

---

## Current status: what works and what does not

### Built and tested (22 test files, ~160 tests)

- Onboarding pipeline: terrain, soil, H3 grid, GeoPackage, DB seed, stream links (pure numpy — no pysheds dependency)
- Village roll-up (P90 + upslope reach + persistence)
- Four-factor confidence (C_in from input layers)
- Physics-first hazard index — live scoring engine
- Stream-blockage check
- Sensor QC / snapping / edge rule
- Two-person alert gate + exercise mode
- CAP 1.2 + Cell Broadcast text generation
- Provenance leakage gate in CI
- Event replay endpoint
- LORO and LOEO validation

### Not built or not working yet

- **ML heads are stubs** (`backend/ml.py`). No trained model is used live; the physics index is the default engine.
- **Flood micro-catchments**: delineation can fail (`KeyError` in the flow-direction step) for some regions; village routes may report `flood: null`.
- **Villages**: regions where OSM Overpass queries fail fall back to `hex_placeholder` or `voronoi_approx` approximations.
- **Not started**: exposure and population priority, evacuation advisory routing, sensor-siting ranking, MQTT live ingest endpoints, LOCO validation, multi-region ablations, SHAP explanations.

---

## Validation — stated honestly

### LORO (Leave-One-Region-Out) — 10 regions, 578 events

| Metric | Value |
|---|---|
| Regions scored | 10 / 10 |
| Events tested | 578 |
| Aggregate detection rate | **94.8 %** |
| False-positive rate | **0.0 %** (event-only test set — no negative samples) |
| C_cal empirical | 1.000 |
| Worst region (Wayanad) | 83.2 % detection (179 events) |

*Run: 2026-09-27 · source: `data/validation/loro_summary.json`*

### LOEO (Leave-One-Event-Out) — 30 events

| Metric | Value |
|---|---|
| Detection rate | 100 % |
| Timing error (mean) | 1 440 min (24 h — rainfall granularity limit) |

*Run: 2026-09-12 · source: `data/validation/calibration.json`*

### Spatial-block cross-validation

Mean detection rate: **0.0 %** (2 clusters, severe data sparsity — not a reliable estimate; reported honestly).

### Risk tier thresholds

| Tier | Score range |
|---|---|
| 🟢 Green | < 30 |
| 🟡 Yellow (Watch) | 30 – 54 |
| 🟠 Orange (Moderate) | 55 – 74 |
| 🔴 Red (High) | ≥ 75 |

Thresholds retained from SRS §10.4 baseline (LOEO DR ≥ 70 % criterion met).

### Earlier ML baseline (57-event table, LORO)

- 24-hour rain alone: ROC-AUC ~0.66
- XGBoost: ROC-AUC ~0.55 (within shuffled-label control range)
- Flash floods (13 events): no learnable signal
- Physics features did not improve this

This is why the live engine is physics-first, not ML. See `data/validation/baseline_v0_results.json`.

### Important caveats

- LORO detection is on the physics-first **index** (not a calibrated probability).
- 0 % false-positive rate reflects the event-only test set — there are no non-event (negative) samples in the LORO fold.
- All thresholds and constants marked *provisional* in the code are defaults, not fitted values.
- Reanalysis rain (ERA5) under-reads extreme events.
- Alerts are a **technical-readiness demonstration**. SACHET / Cell Broadcast accept feeds only from recognised agencies; nothing here publishes. Every Orange/Red alert is a draft held for two-person authorisation.

---

## Design documents

| Document | Purpose |
|---|---|
| [`HydraSense_v2_Merged_Architecture_R1.md`](./HydraSense_v2_Merged_Architecture_R1.md) | Target v2 architecture (authoritative) |
| [`HydraSense_Final.md`](./HydraSense_Final.md) | Earlier region-agnostic architecture |
| [`HydraSense_Gap_Analysis_and_Migration_Plan_v3.md`](./HydraSense_Gap_Analysis_and_Migration_Plan_v3.md) | Migration plan and checklist |
| [`DESIGN_SYSTEM.md`](./DESIGN_SYSTEM.md) | Frontend design tokens and component guide |
| [`SECURITY.md`](./SECURITY.md) | Responsible disclosure policy |
| `CLAUDE.md` | **Deprecated** — kept for history only |

---

## Team

Developed by **Team Vanguard** for Smart India Hackathon 2026.
GitHub organisation: [The-Vanguard](https://github.com/The-Vanguard)
