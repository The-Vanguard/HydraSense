# HydraSense Architecture Analysis

HydraSense is a last-mile downscaling and early-warning layer built on top of India's existing operational flood and landslide guidance systems. 

## High-Level Architecture Overview

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | React 18, Vite, Leaflet | Interactive risk map, hex drill-down, live alert feed |
| **Backend** | FastAPI, Uvicorn, SQLite | REST API, risk engine, CAP alert pipeline |
| **ML** | XGBoost, TabPFN, Chronos-Bolt | Fusion risk model, multi-region inference, time-series forecasting |
| **IoT** | Python MQTT simulator | Sensor ingestion and state management |
| **Data** | H3 hexes, DEM, soil, rainfall | Multi-source feature store |

## Directory Breakdown

### 1. Backend (`/backend`)
The backend is a **FastAPI** application that serves as the core logic engine.
- `main.py`: The entry point of the FastAPI application.
- `routers/`: Contains individual route modules (`risk`, `events`, `simulate`, `alerts`).
- `risk_engine.py`: Contains the core hazard scoring and fusion logic.
- `lead_time.py`: Handles lead-time and factor-of-safety computation.
- `database.py` & `models.py`: SQLite database configuration and SQLAlchemy ORM models.
- `seed.py` / `seed_multiregion.py`: Scripts for seeding Wayanad pilot hexes and multi-region data.
- `scheduler.py` & `notify_ntfy.py`: Alert scheduling and CAP-compliant push notification delivery using ntfy.sh.

### 2. Frontend (`/frontend`)
The frontend is a **React + Vite** SPA focusing on rendering geospatial data.
- Uses **Leaflet** exclusively for map rendering (as per constraints, Mapbox/others are not permitted).
- `src/App.jsx`: Root component handling state management.
- `src/components/`: UI panels including `HexMap`, `ManualScenarioPanel`, `HistoricalEventPanel`, and `AlertFeed`.
- `src/utils/`: Client-side geospatial inference scripts like `pinSimulation.js` for out-of-region coordinates.
- `src/api/`: Handles communication with the FastAPI backend.

### 3. Machine Learning (`/ml`)
The machine learning pipeline predicts flood and landslide risks.
- **Models used**: XGBoost (fusion model), TabPFN, Chronos-Bolt.
- `features/`: Scripts for feature engineering and event-centered sampling.
- `models/`: Logic for XGBoost fusion model training.
- `validation/`: Implements Leave-One-Event-Out (LOEO) cross-validation for robust evaluation.

### 4. IoT Simulation (`/iot`)
Simulates real-world sensor data ingestion.
- `simulator.py`: An MQTT-based simulator that generates simulated sensor states, allowing the system to be tested against "live" data streams without physical hardware.

### 5. Data & Scripts (`/data`, `/scripts`)
- **Data**: Houses H3 hexes (resolutions 8-9), DEM (Digital Elevation Model), soil moisture/texture, and rainfall data. Large generated files are ignored by git but scripts exist to recreate them.
- **Scripts**: Standalone Python utility scripts (e.g., `ingest_dem.py`, `prepare_tabpfn_input.py`, `run_chronos_inference.py`) to manage large datasets and run inferences.

## Core Workflows
1. **Data Ingestion**: Real-time and historical data (weather, terrain, IoT sensor) is ingested via scripts and MQTT into the FastAPI backend.
2. **Risk Computation**: The backend calls the `risk_engine` combining rainfall, soil moisture, terrain (slope, TWI), and vegetation indices. An XGBoost model scores the risk, and a parallel Factor-of-Safety model evaluates slope failure probability.
3. **Alerting System**: If a hex crosses a risk threshold, the alert engine auto-issues a CAP-compliant alert using the `notify_ntfy.py` module to stakeholders.
4. **Dashboard View**: The frontend polls the backend APIs (`/risk/map`, `/alerts/cap`) to visualize the active risk hexes on a Leaflet map.

## Conclusion
The architecture is modular, decoupled by a RESTful API boundary, and heavily leverages open-source geospatial (Leaflet, H3) and ML (XGBoost, FastAPI) libraries to provide scalable and fast risk predictions for hilly regions.
