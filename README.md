# HydraSense

**Region-agnostic flash-flood and landslide decision support for hilly India**

SIH Problem Statement ID: SIH26192

HydraSense is a last-mile downscaling layer on top of India's existing operational guidance
(SAsiaFFGS, GSI). It resolves a place name to terrain, soil, micro-catchments and village areas,
scores risk per H3 hexagon, rolls it up to villages, and drafts CAP 1.2 alerts that are held for
two-person authorisation. Confidence is reported per region and says how much local evidence backs it.

> **Read this first.** The architecture is built; the *validated skill* is not. See
> [Current status](#current-status-what-works-and-what-does-not) before quoting any number.

Authoritative design documents:

- [`HydraSense_v2_Merged_Architecture_R1.md`](./HydraSense_v2_Merged_Architecture_R1.md): target architecture (v2)
- [`HydraSense_Final.md`](./HydraSense_Final.md): earlier region-agnostic architecture
- [`HydraSense_Gap_Analysis_and_Migration_Plan_v3.md`](./HydraSense_Gap_Analysis_and_Migration_Plan_v3.md): migration plan and checklist
- `CLAUDE.md`, `SRS.md`: **deprecated** (kept for history; do not use as constraints)

---

## Architecture

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 18, Vite, deck.gl `H3HexagonLayer`, MapLibre GL (Leaflet kept as fallback) | Risk map, village table, explainability, alert feed |
| Backend | FastAPI, Uvicorn, SQLite (`data/hydrasense.db`) + one GeoPackage per region | REST + WebSocket API, risk engine, CAP pipeline |
| Physics | Infinite-slope FS (Monte Carlo), SCS-CN runoff, stream-blockage check | `backend/engines.py`, `backend/blockage.py` |
| ML | XGBoost heads (landslide, flood) | **Stubs in `backend/ml.py`; see status** |
| IoT | Simulated MQTT publisher; QC, snapping, edge rule as pure logic | `iot/`, `backend/iot_qc.py` |
| Data | H3 res 8, SRTM DEM, SoilGrids, Open-Meteo, IMERG (optional) | Onboarding pipeline + feature store |

## Repository structure

```
backend/
  main.py                 FastAPI app (routers + WebSocket + scheduler lifespan)
  onboarding/             Region onboarding: boundary, DEM, terrain, catchments, villages,
                          SoilGrids, H3 grid, history check, GeoPackage writer, pipeline
  engines.py              E2 slope stability (FS Monte Carlo, I-D threshold), E3 runoff
  blockage.py             E4 stream-blockage check (off without stage sensors)
  classifier.py           Rule-based trigger classifier
  village_rollup.py       Village value from hex risk (P90 + upslope reach), persistence
  confidence.py           Four-factor confidence with reasons
  iot_qc.py               Sensor QC, health, snapping, edge rule
  alerts/                 CAP generator, two-person gate, dedup, WebSocket, Cell Broadcast text
  routers/                risk, region, village, confidence, validation, events, ...
ml/
  features/, models/      Earlier feature / FS / fusion code (pre-v2)
  validation/             LOEO, LORO, spatial-block, calibration
  dataset/                Event geocoding, training-table build, baselines, IMERG comparison
frontend/                 React dashboard (+ Dockerfile, nginx.conf)
iot/                      MQTT simulator
data/                     Events, caches, region GeoPackages (large files are git-ignored)
tests/                    pytest suite
```

## Quick start

Run everything from the repository root (Python 3.12 recommended; the geospatial wheels are
available for it).

```bash
pip install -r backend/requirements.txt -r ml/requirements.txt
uvicorn backend.main:app --reload            # API on http://localhost:8000  (docs at /docs)
```

```bash
cd frontend && npm install && npm run dev    # UI on http://localhost:5173
```

Onboard a region (needs network; writes `data/regions/<code>.gpkg` and seeds `data/hydrasense.db`):

```bash
python -m backend.onboarding.pipeline --region ribhoi-ml --force
```

Tests:

```bash
python -m pytest tests -q --ignore=tests/test_integration_final.py
```

(`tests/test_integration_final.py` is a script that calls `sys.exit()` on import; run it directly.)

Docker (`docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`) is written but
**untested** because Docker was not available where it was authored.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENTOPOGRAPHY_API_KEY` | For live DEM fetch | Used by `backend/onboarding/dem.py` (a cached DEM works without it) |
| `EARTHDATA_TOKEN` | Optional | NASA Earthdata token for IMERG satellite rain (`ml/dataset/fetch_imerg_daily.py`). Never commit it; `.credentials/` is git-ignored |
| `NTFY_TOPIC` | Optional | ntfy.sh topic for push delivery |

## Key API endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/region/resolve` | Resolve a place name to a region |
| GET | `/risk/map`, `/risk/{hex_id}` | Hex risk layer / one hex |
| GET | `/village/priority?region=`, `/village/{id}/risk?region=` | Village roll-up (risk-only ranking; flood side not built) |
| GET | `/confidence/{hex_id}/factors` | Four-factor confidence with reasons and stated assumptions |
| GET | `/validation/loeo`, `/validation/loro` | Stored validation results |
| POST | `/alert/trigger`, `/alert/gate/approve` | Draft an alert / second-person authorisation |
| WS | `/ws/alerts` | Live feed |

---

## Current status: what works and what does not

**Built and tested (about 160 tests):** onboarding pipeline (terrain, soil, H3 grid, GeoPackage, DB seed),
village roll-up, four-factor confidence, blockage check, sensor QC / snapping / edge rule,
two-person alert gate, Cell Broadcast text, provenance leakage gate in CI.

**Not built or not working yet:**

- **ML heads are stubs** (`backend/ml.py`). No model is trained for serving.
- **Flood side is empty:** micro-catchment delineation fails (`KeyError` in the flow-direction step),
  so there is no per-catchment flood value; village routes report `flood: null`.
- **Villages are placeholders** for regions where the OpenStreetMap queries fail (labelled
  `hex_placeholder`); Voronoi villages (`voronoi_approx`) need Overpass to respond.
- **Not started:** exposure and priority, evacuation advisory, sensor-siting ranking, MQTT ingest
  endpoints, LOCO validation, ablations, multi-region back-test, region-agnostic replay pilot, SHAP.

**Validation, stated honestly:**

- Event data: 57 graded real events in 11 regions (`data/events/historical_events.csv`); 54 are in scope
  and only 24 can be placed in a single H3 hex from published coordinates.
- Baseline on the resulting table (leave-one-event-out, 39 landslide events): 24-hour rain alone
  reaches ROC-AUC about 0.66; XGBoost about 0.55, which is within the range of a shuffled-label
  control. Flash floods (13 events) show no learnable signal. Physics features did not change this
  (`data/validation/baseline_v0_results.json`, `baseline_v0p_results.json`).
- Satellite rain (GPM IMERG Final, daily) was compared with ERA5 on the same rows, leak-free daily
  features, leave-one-event-out: no meaningful difference (landslide XGBoost 0.58 vs 0.57 ROC-AUC,
  logistic 0.60 vs 0.65; flash floods at chance for both). An early partial run that favoured IMERG
  was a subset artefact (`data/validation/imerg_vs_era5_results.json`).
- The stored LORO summary (`data/validation/loro_summary.json`) has no negative samples (0% false
  positives) and must not be quoted; `C_cal` therefore defaults to a provisional 0.75.
- All thresholds and constants marked *provisional* in the code are defaults, not fitted values.
- Reanalysis rain under-reads extreme events (`docs/data_limitations.md`).

Alerts are a **technical-readiness demonstration**. SACHET / Cell Broadcast accept feeds only from
recognised agencies, so nothing here publishes; every Orange/Red alert is a draft held for two-person
authorisation.

## Team

Developed by Team Vanguard for Smart India Hackathon 2026.
GitHub organisation: [The-Vanguard](https://github.com/The-Vanguard)
