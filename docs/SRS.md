---
title: "HydraSense — Software Requirements & Reference Specification (SRS)"
subtitle: "Hyper-Local Flash Flood & Landslide Downscaling Layer for Hilly Regions"
problem_statement_id: "SIH26192"
pilot_region: "Wayanad, Kerala (Mundakkai / Chooralmala / Attamala / Punjirimattom)"
version: "SRS v2.0 — FINAL, all open issues from QA review resolved and frozen"
team_size: 6
build_window: "3 days (~72 hours)"
---

**How to use this document:** this file is the single source of truth for the project —
problem, architecture, data, models, schema, APIs, references, and a phase-by-phase build
plan. Each phase in Section 25 ends with a ready-to-paste prompt for Claude Code or
Antigravity. Check this file into the repo root as `SRS.md`, alongside a `CLAUDE.md`
containing Section 26's constraints, and point every coding session at both before it writes
anything.

**This is v2.0 — the final, frozen version.** Every ambiguity, contradiction, and undefined
formula flagged in the v1.0 QA review has been resolved below. Where v1.0 said "decide this"
or left a formula undefined, this version states the decision and the formula directly — no
open items remain. If any future prompt or judge question surfaces something this document
doesn't cover, update this file directly; don't let the answer live only in chat history.

---

## 1. Problem Statement

SIH26192 — Flash Flood Prediction System for Hilly Regions using Multi-Source Data.

India's existing operational systems for this problem are real and already deployed:

- **SAsiaFFGS** (South Asia Flash Flood Guidance System) — rainfall + soil-moisture + ML
  based flash-flood guidance at 4km/district-scale resolution, 6–24 hour lead time,
  operational since October 2020, run by IMD as the WMO's Regional Centre for the system.
- **GSI RLFS** (Geological Survey of India Regional Landslide Forecasting System) — regional
  rainfall-threshold-based landslide forecasting, launched 2020, growing out of the
  LANDSLIP project; operational bulletins now cover 21 districts across 8 states.

The gap is not forecasting science — it's resolution and relay speed. A 4km grid cell can
span several villages with completely different slope, drainage, and soil conditions. And
even after a forecaster sees elevated risk, there is a manual, human-mediated relay step
before a public alert is issued through Sachet (India's Common Alerting Protocol platform).

HydraSense does not replace SAsiaFFGS or GSI. It is a downscaling and last-mile layer: it
takes their coarse guidance down to village/ward resolution using local terrain physics, and
it closes the relay gap by auto-generating and pushing a CAP-compliant alert the moment a hex
crosses a risk threshold — no forecaster in the loop for that specific step.

---

## 2. Product Positioning

**Name:** HydraSense

**One-liner:** A last-mile downscaling layer for India's existing flash-flood and landslide
guidance systems — not a replacement for either. Takes SAsiaFFGS's 4km/district output and
GSI's regional landslide guidance down to village/ward resolution via H3 hexes, replaces the
rainfall-threshold landslide bolt-on both systems rely on with a physically coupled
Factor-of-Safety model carrying an explicit uncertainty band, and removes the manual
forecaster-relay step between a risk score and a Sachet alert.

**The claim to make to judges, verbatim:**
> "SAsiaFFGS already does rainfall + soil moisture + ML at 4km, district-scale resolution,
> with a 6–24 hour lead time, operational since 2020. GSI separately issues
> rainfall-threshold-based landslide forecasts at a regional level. We are not rebuilding
> either. We are the downscaling and last-mile layer neither provides: village-level
> resolution via H3 hexes, a physics-coupled landslide model with an explicit confidence band
> instead of a rainfall-threshold bolt-on, an algorithmically computed lead time instead of a
> fixed guidance window, and a direct CAP-to-Sachet push that skips the manual
> forecaster-relay step both systems' outputs currently require."

**The claim to avoid:** "India's first AI flood prediction system," or anything implying
HydraSense replaces or competes with SAsiaFFGS/GSI rather than extending them. If asked "so
what do you actually add?", the one-breath answer above is the whole point of this framing —
don't drift from it under pressure.

---

## 3. Scope

### 3.1 In scope (build this)

- Village/ward-resolution (H3 res 8–9) risk scoring for one pilot cluster (Wayanad)
- Physics-based Factor-of-Safety slope stability model, with an explicit uncertainty band
- XGBoost fusion model combining terrain susceptibility + rainfall/soil hazard signals
- Event-based Leave-One-Event-Out (LOEO) validation with event-centered temporal sampling
  and a fully specified label scheme (Section 11)
- Algorithmically computed lead-time-to-Red, derived from **hourly** forecast rainfall — see
  the frozen decision in Section 12
- A combined confidence index (model certainty × physical uncertainty)
- Auto-generated CAP 1.2 XML alerts on Orange/Red crossing, routed to a mock Sachet webhook,
  with deduplication and downgrade handling (Section 17)
- A live dashboard: hex heatmap, trend view, feature-contribution panel, validation-results
  panel
- Simulated IoT sensor input (MQTT) with a scripted sensor-dropout fallback demo beat
- A live/cached-demo fallback for the one external API called repeatedly on stage

### 3.2 Explicitly out of scope — say this out loud, don't let it get built by accident

- Exposure/impact modeling: population weighting, school/hospital/road exposure, live
  safe-route computation. A static shelter lookup table stands in for this in the demo.
- Real, authorized machine-readable integration with SAsiaFFGS or GSI RLFS — both are
  represented as clearly labeled simulated proxy signals, not live institutional integrations.
- Full hydrodynamic (SCHISM-class) inundation modeling — a simplified Manning's-equation
  raster only, gated to compute only when tier ≥ Orange.
- LoRaWAN hardware — IoT is simulated via MQTT.
- Real-time LLM-based national news mining — historical events are a manually compiled
  spreadsheet.
- NASA SMAP soil-moisture integration — NASA POWER is the only soil-moisture source in scope.
- District- or state-wide coverage — one pilot cluster only.
- A live-recomputed LOEO validator — validation runs once offline; results are read from a
  static table, never recomputed on stage.

---

## 4. Three-Layer Risk Model

```
SUSCEPTIBILITY (static, terrain-derived, computed once)
   slope, aspect, TWI, TRI, drainage density, distance-to-stream, soil permeability proxy,
   land cover, NDVI, GSI susceptibility class, historical event density
        ×
HAZARD (dynamic, recomputed every ingestion cycle)
   rainfall at multiple windows, antecedent precipitation index, soil saturation, Factor-of-
   Safety (+ uncertainty band), simulated FFGS/GSI proxy signals, IoT anomaly flag
        +
EXPOSURE — ROADMAP ONLY, NOT BUILT
   population count, road segments, school/hospital points, live safe-routing
        =
RISK SCORE per H3 hex (0–100), tier (Green/Yellow/Orange/Red), confidence_score (0–100),
algorithmically computed lead_time_min
```

The exposure leg is real disaster-risk science and belongs on the roadmap slide, but nothing
in it is live in the demo. What's shown live is susceptibility × hazard → risk score → tier →
confidence → lead time. The demo's evacuation line comes from a static shelter lookup, not a
computed exposure model — state this proactively; it's a credibility asset, not a weakness to
hide.

---

## 5. Pilot Region — Frozen Before Any Code Is Written

- **Region:** Wayanad district, Kerala
- **Villages/catchments:** Mundakkai, Chooralmala, Attamala, Punjirimattom
- **Why this region:** the July 2024 Wayanad landslide disaster is recent, extremely
  well-documented, sits in a data-rich state, and now has site-specific published geotechnical
  data (Section 18).
- **Prediction horizon:** 6–24 hours (matches SAsiaFFGS's own lead-time envelope)
- **Spatial unit:** H3 resolution 8–9 (~0.1–0.7 km² per hex), roughly village/ward scale

> **Frozen decision (resolves the old "4 pilot hexes" ambiguity):** the pilot cluster is
> **4 named villages**, not 4 hexes. The H3 res 8–9 grid is generated to cover those four
> village polygons, producing however many hexes that naturally requires — this will be more
> than 4. Every reference elsewhere in this document to "the 4 pilot hexes" is superseded by
> this: say "the 4 pilot villages / N pilot hexes" instead, where N is whatever the grid
> generator produces. This is not a cosmetic fix — it's the actual point of the product
> (village-level resolution, not one blob per village).

---

## 6. System Architecture

### 6.1 Data flow (build-time / continuous pipeline)

```
Open-Meteo          OpenTopography         NASA POWER          ESA WorldCover        GSI Bhukosh
(rainfall+forecast)  (SRTM 30m DEM)      (soil moisture proxy)  (land cover, NDVI)  (susceptibility —
      │                    │                     │                     │             manual, Sec.8)
      └────────────────────┴─────────────────────┴─────────────────────┴─────────────────┘
                                          ↓
                          INGESTION & STORAGE (FastAPI + PostGIS, H3 grid res 8–9)
                                          ↓
                ┌─────────────────────────┴─────────────────────────┐
                ↓                                                   ↓
      STATIC FEATURES (11)                                HAZARD FEATURES (14)
      susceptibility, computed once                        recomputed every cycle
                └─────────────────────────┬─────────────────────────┘
                                          ↓
                              RISK MODELS (Section 10)
                ┌─────────────────────────┴─────────────────────────┐
                ↓                                                   ↓
     FS MODEL (physics, infinite-slope,                  FUSION MODEL (XGBoost,
     min/max uncertainty band)                            trained on ~30–50 events)
                └─────────────────────────┬─────────────────────────┘
                                          ↓
                    risk_scores per hex: score, tier, confidence, lead_time
```

> **Frozen correction:** the static/dynamic feature counts above are **11 static + 14
> dynamic = 25 features** total (not 24 — see Section 9's frozen note).

### 6.2 Runtime workflow (every ingestion cycle)

```
New ingestion cycle (rainfall + soil + IoT arrive)
        ↓
Recompute features (static + dynamic joined per hex)
        ↓
Run FS + fusion model (physics band + XGBoost score)
        ↓
Risk score & tier (0–100, Green→Red, confidence)
        ↓
Tier check: Orange/Red?
  ┌───────────┴───────────┐
 YES                       NO
  ↓                         ↓
Alert pipeline:         Dashboard update:
CAP XML → Sachet,       heatmap, trend,
SMS log, dashboard      confidence panel
  ↓
Dedup check (Section 17): only fire if tier increased since
last alert for this hex, or the cooldown window has elapsed
```

Two computations sit outside this per-cycle loop:
- **Lead-time** (Section 12) reruns the trained model against forecast rainfall, separately,
  only for hexes still below Red.
- **LOEO validation** (Section 11) is offline and one-time (or once per retrain) against the
  historical event set — its output just populates `loeo_results` for the validation panel to
  read.

This is a stateless recompute loop, not event-driven — every hex gets features and models
rerun every cycle regardless of whether anything changed. That's the right call for a 3-day
build: simple, debuggable, no message-queue infrastructure needed. If asked about this at
scale: "for the pilot cluster's hex count this is trivially fast; production would move to
change-triggered recompute — a scaling optimization, not a correctness issue."

---

## 7. Technology Stack

No component here is exotic or has real adoption risk for a CS team — the execution risk in
this project is scope and sequencing, not tooling. **All choices below are frozen — no "or"
options remain.**

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (Python) | Fast to scaffold, async-friendly, plays well with geospatial libs |
| Database | PostgreSQL + PostGIS | Native geospatial support; skip TimescaleDB unless someone already knows it cold |
| Spatial grid | Uber H3, resolution 8–9 | Hexagonal uniform-area cells, standard library support |
| Terrain processing | **pysheds** (frozen — see Section 20) | Pure Python, pip-installable, no external compiled binary; flow accumulation, TWI, TRI, stream extraction |
| ML model | XGBoost (frozen — PSO-BP is never implemented) | Trains in seconds, gives feature importances free, realistic to validate from scratch in the time available |
| Alerting | CAP 1.2 XML | Open OASIS standard, the exact format Sachet ingests |
| IoT simulation | MQTT (e.g. Mosquitto broker) | Standard pub/sub, easy to script an escalation curve |
| Frontend map | **Leaflet** (frozen — see Section 20) | No key/signup dependency, nothing that can fail live on stage |
| Data interchange | Parquet / JSONB in PostGIS | Precomputed static features stored once, hazard features as JSONB per cycle |

---

## 8. Data Sources & Availability Audit

Verified live at time of writing, not assumed from training data — each source below was
checked for actual current access before being included.

| Need | Real/ideal source | Build-scope source (verified free & instant) | Status |
|---|---|---|---|
| Rainfall (current + forecast) | IMD Mausam/AWS | **Open-Meteo API** — free, no key, hourly + hourly forecast (forecast series required for Section 12) | ✅ Confirmed |
| DEM (30m) | ISRO Bhuvan DEM | **SRTM 30m via OpenTopography API** — free, instant API key | ✅ Confirmed |
| Soil moisture | — | **NASA POWER API only** — free, no key. Native resolution ~50km — a real, permanent accuracy ceiling, not a build defect. `GWETROOT` field used directly as `soil_saturation_ratio` (Section 10). NASA SMAP explicitly excluded (Earthdata login + HDF5/NetCDF processing, no accuracy gain at hex scale) | ✅ Confirmed, coarse |
| Land cover (`land_use_class`) | ISRO Bhuvan LULC | **ESA WorldCover 10m** — free, no key, no signup, direct pull from public `s3://esa-worldcover/` bucket | ✅ Confirmed |
| Vegetation index (`ndvi_mean`) | Sentinel-2 via Earth Engine | Same ESA WorldCover project's NDVI percentile composites — same free bucket | ✅ Confirmed |
| Landslide susceptibility class (`gsi_susceptibility_class`) | GSI Bhukosh/NGDR | No bulk-download API exists — confirmed by checking the live portal (map viewer + district bulletin selector only). Manual hand-read for the pilot hexes, budget 1–2 hours | ⚠️ Manual, bounded |
| Historical landslide/flood inventory | GSI Bhukosh | Manually compiled 30–50 events from public news + the Mundakkai-Chooralmala papers (Section 18) | ⚠️ Manual; coordinate precision from news sources is village-level, not point-level — tagged explicitly (Section 11) |
| SAsiaFFGS guidance signal | Not publicly API-accessible | Simulated: rainfall-threshold rule, clearly labeled | N/A — proxy by design |
| GSI RLFS guidance signal | Not publicly API-accessible | Simulated: rainfall + susceptibility-class rule, clearly labeled — depends on `gsi_susceptibility_class` above | N/A — proxy by design |
| Soil geotechnical parameters (c′, φ′, γ, z) | Generic regional literature | Site-specific values from the Mundakkai-Chooralmala Scientific Reports paper (Section 18), direct shear tests at the actual pilot site | ✅ Confirmed, unusually strong for a hackathon |
| Sachet webhook | NDMA Sachet | No public API exists — mock webhook only | N/A by design, not a gap |
| Satellite verification (stretch) | Sentinel-1 SAR | Skip entirely; roadmap only | Out of scope |

**Rule for the team:** if a source needs manual approval/registration with unknown turnaround,
don't touch it in the first 12 hours. GSI susceptibility class is the one deliberate
exception — small and bounded, so it gets a scheduled owner and hour slot (Section 21), not a
skip. Do not spend time hunting for a GSI bulk-inventory export — verify it exists in the
first hour if you want to check, but the manual-compile fallback above already covers this
either way.

---

## 9. Feature List (25 features)

> **Frozen correction:** earlier drafts of this document claimed "24 features" (11 static +
> 13 dynamic). That count was wrong — `iot_anomaly_flag` was left out. The real, correct count
> is **11 static + 14 dynamic = 25 features.** Nothing is removed; this is a counting fix only.

**Static (susceptibility) — 11 features, computed once per hex from the DEM/land-cover layers:**
`slope_deg`, `aspect`, `TWI`, `TRI`, `elevation`, `distance_to_stream_m`, `drainage_density`,
`land_use_class`, `ndvi_mean`, `historical_event_count_500m`, `gsi_susceptibility_class`

**Dynamic (hazard) — 14 features, recomputed every ingestion cycle:**
`rainfall_1h`, `rainfall_3h`, `rainfall_6h`, `rainfall_24h`, `rainfall_72h_antecedent`,
`rain_intensity_mm_hr`, `antecedent_precipitation_index` (renamed from `api_score` — see the
frozen note below), `soil_saturation_ratio`, `factor_of_safety`, `factor_of_safety_min`,
`factor_of_safety_max`, `simulated_ffgs_signal`, `simulated_gsi_signal`, `iot_anomaly_flag`

**Derived output fields (not model input):** `confidence_score`, `lead_time_min`

**Explicitly removed from build:** `population_est`, `has_school`, `has_hospital`,
`road_segment_count` — roadmap bullet only, never computed or displayed as if computed.

> **Frozen decision — field rename:** the feature formerly named `api_score` is renamed to
> `antecedent_precipitation_index` everywhere in code, schema, and UI. The old name was
> ambiguous with "Application Programming Interface." If `api_score` appears anywhere as a
> legacy label, it must carry an inline comment: `api_score = Antecedent Precipitation Index,
> not an API endpoint.`

---

## 10. Models

### 10.1 Factor of Safety — infinite-slope physics model (build first)

```
FS = [c' + (γ − γw·m)·z·cos²(β)·tan(φ')] / [γ·z·sin(β)·cos(β)]
```
- `β` = slope angle (from DEM)
- `m` = saturation ratio, 0–1 (from `soil_saturation_ratio` — see the frozen formula below)
- `c'`, `φ'`, `z`, `γ` = cohesion, friction angle, depth, unit weight — primary source: the
  Mundakkai-Chooralmala Scientific Reports paper (Section 18), site-specific to the pilot
  area. Supplement with published Kerala/coastal laterite ranges only where the paper's
  sampled points don't cover a hex's soil type.
- `FS < 1.0` → slope failure predicted; feed `1/FS` (clipped) into the fusion model

**Uncertainty band (no Monte Carlo):** compute FS twice per hex per cycle — once with the
worst-case parameter combination, once with best-case — giving `factor_of_safety_min/max`
directly from two deterministic evaluations of the same closed-form equation. A band
straddling FS=1.0 is itself informative: the physics is genuinely uncertain for that hex.

> **Frozen formula — `soil_saturation_ratio`:**
> ```
> soil_saturation_ratio = GWETROOT   # NASA POWER's root-zone soil wetness, already a 0–1 fraction
> ```
> No new formula needed to invent — NASA POWER already exposes this as a normalized fraction
> of saturation. This value is spread onto each hex from NASA POWER's coarse (~50km) grid via
> nearest-grid assignment, and must be labeled a **"soil saturation proxy"** everywhere it
> appears in the UI — never described as a village-level measurement (see Section 8).

### 10.2 Fusion model — XGBoost (frozen default; PSO-BP is never implemented)

Train on the ~30–50 hand-compiled historical events (positive labels, expanded via
event-centered sampling — Section 11) plus randomly sampled non-event hex-timesteps (negative
labels, sampling rules frozen in Section 11). Output: `risk_score` (0–100) per hex per cycle,
plus feature contributions for the explainability panel, plus the model's own class
probability for the predicted tier (used in the confidence score below).

> **CLAUDE.md hard constraint, restated here:** XGBoost only. PSO-BP must never be suggested
> or implemented, under any circumstances, regardless of framing.

> **Frozen formula — `risk_score`:** a probability-weighted expected value over XGBoost's
> four tier-class probabilities, not a raw argmax pick — this keeps the score continuous and
> avoids visible jumps when the top predicted class flips near a boundary.
> ```
> risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88
> ```
> (midpoints of each tier's 0–100 band; the four `P()` values come from XGBoost's
> `predict_proba`). Tier is then derived from `risk_score` using the thresholds in Section
> 10.4, so score and tier stay mutually consistent by construction.

### 10.3 Confidence score

```
confidence_score = 100 × model_class_probability × (1 − FS_band_width_penalty)
```
`FS_band_width_penalty` is a small, capped term — 0 if the FS band doesn't straddle 1.0,
rising toward ~0.3 as the band widens and straddles the failure threshold. Show this
everywhere the risk score appears. This is a confidence index, not a calibrated probability —
never present it as "88% probability of landslide."

### 10.4 Tiering

`Green: 0–29 | Yellow: 30–54 | Orange: 55–74 | Red: 75–100`
Orange/Red triggers the alert path (with dedup logic, Section 17) and the simplified 2D
inundation view.

---

## 11. Validation — Event-Based Leave-One-Event-Out (LOEO)

Why this is a precondition, not a parallel workstream: the lead-time and confidence numbers
are only defensible if you can show how they were checked against real, labeled events. Build
this before polishing lead-time or confidence display.

### 11.1 Target definition (frozen)

The model's target is **forward-looking**: for each hex-timestep, predict whether this hex is
in an *escalating pre-event state* — not "did an event already happen here." This is what
makes the lead-time claim honest: the model is trained to recognize the shape of an
approaching event, not to classify it after the fact.

### 11.2 Event-centered temporal sampling & tier labels (frozen)

Expand each compiled historical event into time-stepped samples at 72h/48h/24h/12h/6h before
the recorded event time, using the actual observed rainfall/soil trajectory. Each snapshot
carries its own **escalating tier label**, not one flat "positive" tag:

| Snapshot | Tier label |
|---|---|
| 72h before event | Yellow |
| 48h before event | Yellow |
| 24h before event | Orange |
| 12h before event | Orange |
| 6h before event | Red |
| Event time | Red |

This gives the model more rows to learn the *shape* of an escalating episode, not just its
endpoint. **Critical distinction for judges:** the extra timesteps increase training signal,
they do **not** increase independent validation episodes — LOEO still holds out and scores at
the event level (~30–50), and that's the number you report as your validation sample size,
never the larger timestep count.

### 11.3 Positive sample definition (frozen)

The positive-labeled hex(es) for an event are those where the failure was physically
reported. If only village-level precision is available (the common case for news sources),
label **all** hexes covering that village polygon as positive, but tag them
`coordinate_precision: village-level` in the metadata — visible in the schema and the
validation panel, never hidden.

### 11.4 Negative sample definition (frozen)

Sampled from two pools, capped at a **4:1 negative:positive ratio**:
1. The same pilot hexes, on dates ≥30 days from any recorded event (baseline "normal" state).
2. Other pilot hexes during a real storm period that did **not** report a failure (harder
   negatives — teaches the model that rain alone isn't sufficient).

Exclude any timestep within **7 days** of a labeled positive event from the negative pool
entirely, to prevent leakage. All negatives get `tier: Green`.

### 11.5 Hex-event assignment table (frozen requirement)

Build this table **before training starts** — it is the training set, not a byproduct of it:

`event_id | hex_id | timestamp | label | tier | coordinate_precision`

Do not let two team members build this independently from the raw event list; there must be
one canonical table.

### 11.6 LOEO method

For each event E:
1. Train on all other events (leave E and all its timesteps out entirely, including any
   hex-timesteps within a reasonable window of E's timestamp, to avoid leakage).
2. Run the trained model forward through E's actual observed time series, hex by hex.
3. Check: did the tier cross Orange/Red before or at the reported event time (detection)? If
   so, how far before (timing error, compared to the historical record's reported time — rough
   ground truth is fine, don't require minute-precision you don't have)?
4. Aggregate across all events: detection rate, false-positive rate on negative samples,
   mean/median timing error with spread, including worst cases — report honestly, not just
   best-case events.

**Scope discipline:** this is offline, one-time (or once per retrain), reported as a static
results table — never recomputed live on stage.

---

## 12. Lead-Time Estimation — Algorithmic Time-to-Red

> **Frozen decision (resolves the old t+10/t+20/t+30-minute ambiguity):** lead-time is
> computed at **hourly forecast horizons only — t+1h, t+2h, t+3h, ... up to the prediction
> horizon (6–24h)**. Open-Meteo's forecast series is hourly, full stop; no interpolated or
> invented sub-hour numbers are shown in the demo. `lead_time_min` is still expressed in
> minutes for the UI (e.g. a t+2h crossing displays as "120 min"), but the underlying
> computation never resolves finer than one hour.

**Method, runs per ingestion cycle, per hex currently below Red:**
1. Pull Open-Meteo's hourly forecast rainfall series (not current observation) out to the
   prediction horizon (6–24h).
2. At each forecast horizon step, recompute the rainfall-dependent dynamic features using
   forecast rainfall instead of observed, and rerun the trained fusion model.
3. `lead_time_min` = the first forecast horizon where the projected tier reaches Red,
   expressed in minutes. If no horizon crosses, set `lead_time_basis` to
   `"no_red_crossing_in_forecast_window"` and `lead_time_min` to null — a legitimate, honest
   output state, not a failure to hide.

This reruns an already-trained, already-validated model against a different input series — no
new model, no new training. Show which forecast horizon triggered the crossing on the
dashboard (e.g., "projected Red at t+2h based on Open-Meteo forecast") — this doubles as your
honest answer to "what if the forecast is wrong."

---

## 13. Live/Demo Data-Source Fallback

The live demo must never depend on a single successful HTTP call at the exact moment you're
on stage.

```
request Open-Meteo (current + forecast)
        ↓
   success within 3–5s timeout?
   ┌────────┴────────┐
  YES                NO
   ↓                  ↓
live data      cached demo snapshot
```

> **Frozen caching strategy:** pre-fetch and store a full rainfall + forecast snapshot for the
> pilot cluster before demo day. The live call uses a 3–5 second timeout; on timeout or error,
> fall through automatically to the cached snapshot — no manual intervention, no visible
> glitch. No further caching infrastructure is needed for a 3-day build.

Show a small, honest "Data source: LIVE / Data source: CACHED DEMO" label on the dashboard
always. This applies specifically to the Open-Meteo call made live and repeatedly during the
demo — it's separate from the IoT sensor-dropout fallback (Section 15), which is a deliberate
scripted demo beat, not a safety net.

---

## 14. Database Schema (PostgreSQL + PostGIS)

```
hexes(hex_id, geom, static_features JSONB)

observations(hex_id, timestamp, dynamic_features JSONB)
-- dynamic_features JSONB includes factor_of_safety_min/max, simulated_gsi_signal,
-- antecedent_precipitation_index (renamed from api_score, Section 9)

risk_scores(hex_id, timestamp, risk_score, tier, confidence_score, lead_time_min,
            lead_time_basis TEXT, feature_contributions JSONB, data_source TEXT)
-- lead_time_basis records whether the value is a real forecast-horizon crossing
-- or "no_red_crossing_in_forecast_window"
-- data_source is "live" or "cached_demo" (Section 13)

historical_events(event_id, hex_id, date, type, severity, source, coordinate_precision TEXT)
-- coordinate_precision is "village-level" or "point-level" (Section 11.3)
-- this table is also the LOEO validation set — do not maintain a separate copy

loeo_results(event_id, detected BOOL, crossing_tier TEXT, timing_error_min INT, notes TEXT)
-- populated once by the offline LOEO run, read by the validation panel

alerts(alert_id, hex_id, timestamp, tier, cap_payload JSONB, delivered_channels TEXT[])

alert_state(hex_id PRIMARY KEY, last_alert_tier TEXT, last_alert_timestamp TIMESTAMP,
            consecutive_below_orange_cycles INT DEFAULT 0)
-- new table, backs the dedup/downgrade logic in Section 17

shelters(shelter_id, name, hex_id, lat, lon)
-- small static hand-entered lookup (5-10 real Wayanad shelter locations)
-- nearest-shelter-by-hex via simple distance sort, NOT live routing
```

---

## 15. API Contracts (FastAPI)

```
POST /ingest/rainfall            { hex_id | lat, lon, timestamp, value_mm }
POST /ingest/rainfall_forecast   { hex_id | lat, lon, forecast_series }
POST /ingest/soil_moisture       { hex_id | lat, lon, timestamp, value_pct }
POST /ingest/iot                 { device_id, hex_id, timestamp, sensor_type, value, battery }

GET  /risk/{hex_id}              -> risk_score, tier, confidence_score, lead_time_min,
                                     lead_time_basis, top_contributing_features,
                                     data_source ("live" | "cached_demo")
GET  /risk/map?bbox=...          -> all hex risk scores in a bounding box (dashboard heatmap)
GET  /risk/{hex_id}/history       -> time series of risk_score (1D trend view)
GET  /risk/{hex_id}/inundation    -> simplified 2D inundation raster, ONLY if tier >= Orange
GET  /risk/{hex_id}/uncertainty   -> factor_of_safety_min/max band + confidence_score breakdown

GET  /validation/loeo             -> aggregated LOEO results table, served static

GET  /shelters/nearest/{hex_id}   -> nearest static shelter lookup

POST /alert/trigger              -> internal, auto-called on Orange/Red crossing; applies the
                                     dedup/downgrade check (Section 17) before generating CAP
                                     XML, logs to alerts, fans out to mock SMS/dashboard
GET  /alert/feed                 -> list of active alerts for the dashboard
```

Keep the inundation endpoint gated behind the Orange/Red check in code, not just the UI.

---

## 16. IoT Simulation Spec

- Python script publishing synthetic MQTT messages on `sensors/{hex_id}/rainfall`,
  `sensors/{hex_id}/soil_moisture`, `sensors/{hex_id}/tilt`.
- Replays a scripted escalation curve for the pilot hexes (Section 22) rather than random
  noise.
- Includes one sensor going offline mid-demo, with the dashboard visibly falling back to an
  **"external-data-only estimate"** for that hex — demonstrates sensor-health fallback without
  real hardware.

> **Frozen wording correction:** the fallback label is **"external-data-only estimate,"** not
> "NWP/satellite-only estimate." The build only uses Open-Meteo (a weather model, not a
> satellite instrument) and NASA POWER (also model-derived); calling this "satellite-only"
> overstates what's actually behind it.

---

## 17. Alert Behavior — Deduplication, Downgrade, and CAP Output

### 17.1 Deduplication (frozen)

A new CAP alert fires only when a hex's tier **increases** past the tier of its last-sent
alert for that hex, or after a fixed **30-minute cooldown** if the tier stays the same. This
is backed by the `alert_state` table (Section 14): check `last_alert_tier` and
`last_alert_timestamp` before calling `/alert/trigger`'s CAP-generation step.

### 17.2 Recovery / downgrade behavior (frozen)

A tier drop is **never** re-sent as a new CAP alert. Instead:
- Log a "downgrade" event to the dashboard/alert feed (visually distinct from an urgent alert).
- Require the hex to stay below Orange for **2 consecutive ingestion cycles**
  (`consecutive_below_orange_cycles >= 2` in `alert_state`) before marking it "resolved" on
  the dashboard — this avoids flapping between tiers on noisy input.

### 17.3 CAP 1.2 XML output format

```xml
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>HYDRASENSE-WYD-2026-000123</identifier>
  <sender>hydrasense.sih2026@example.org</sender>
  <sent>2026-08-30T14:32:00+05:30</sent>
  <status>Actual</status>
  <msgType>Alert</msgType>
  <scope>Public</scope>
  <info>
    <category>Geo</category>
    <event>Flash Flood / Landslide Risk</event>
    <urgency>Immediate</urgency>
    <severity>Severe</severity>
    <certainty>Likely</certainty>
    <headline>High flash-flood/landslide risk: Mundakkai, Wayanad</headline>
    <description>Risk score 82/100 (RED), confidence 88/100. Estimated lead time 120 minutes
    (t+2h forecast-horizon crossing, Open-Meteo). Nearest known shelter: Shelter S2 (static
    lookup).</description>
    <area>
      <areaDesc>Mundakkai ward, Wayanad</areaDesc>
      <polygon>...H3 hex boundary coordinates...</polygon>
    </area>
  </info>
</alert>
```
> Note the description's lead-time example is now hour-granular ("120 minutes, t+2h crossing")
> per Section 12's frozen decision — not the old 35-minute example, which implied
> sub-hour forecast precision the data doesn't actually support.

Route to: a mock "Sachet-compatible" webhook, a simulated SMS log, and the dashboard alert
feed.

---

## 18. Research Papers & References Used

1. Mundakkai-Chooralmala landslide: assessment of initiation, progression, and impact.
   *Scientific Reports* (2025). https://www.nature.com/articles/s41598-025-07828-3 —
   multidimensional assessment (hydrometeorology, geology, geotechnical, geomorphology,
   damage) of the July 30, 2024 event, including geotechnical/laboratory parameters used at
   the actual pilot site. Primary source for Section 10.1's Factor-of-Safety soil parameters.
2. Achu, A.L., Aju, C.D., Thomas, J. et al. — "Decoding the dynamics of July 2024
   Mundakkai-Chooralmala landslide in Kerala (India): an analysis of formation mechanisms,
   impacts and lessons learned." *Landslides* (2025).
   https://doi.org/10.1007/s10346-024-02454-y — field observations, aerial imagery, and
   rainfall-data analysis of the same event; useful secondary source for historical event
   compilation (Section 11) and rainfall-threshold context.
3. Kolathayar, S., Menon, V. & Kundu, P. — "Landslides and debris flow triggered by the July
   2024 extreme rainstorm in the Chooralmala watershed in Wayanad, India." *Landslides* 22,
   967–974 (2025). https://doi.org/10.1007/s10346-024-02443-1 — rainfall-gauge data and
   antecedent-rainfall analysis for the same event; a second independent source for
   cross-checking event timing.
4. Geological Survey of India — First Information Report (FIR), Mundakkai-Chooralmala
   Landslide. https://bhusanket.gsi.gov.in/Public_Portal_News_pdf/FIR_Mundakkai-Chooralmala.cleaned.pdf
   — official field-assessment report; useful for event severity/impact-area details.
5. Wang et al. (2024) — PSO-BP validated on 103 ungauged hilly watersheds, MAE 2.51%, RMSE
   3.74%. Cited only as a method reference for context; **PSO-BP itself is never implemented in
   this build** (Section 10.2) — do not cite this as your own achieved accuracy.

**Use policy:** cite these by name in the pitch deck and any written report; do not reproduce
figures, tables, or substantial text from them verbatim — summarize findings in your own
words per standard citation practice.

---

## 19. Feasibility, R&D, and Betterment Assessment

Directional judgments, not a rigorously derived index — state them narratively in the pitch
if asked, not as a single inflated composite score.

| Axis | Rating | One-line justification |
|---|---|---|
| Core software architecture | 9/10 | FastAPI/PostGIS/H3/XGBoost/MQTT/CAP are all mature, verified-accessible, zero adoption risk |
| Data availability (as prototype) | 8/10 | Every source is confirmed free & live; the only manual item (GSI class) is small and bounded |
| R&D depth | 5.5/10 | Mostly applied engineering on known techniques; event-centered LOEO sampling is the one genuine methodological addition |
| Feasibility (3-day, 6-person build) | 8/10 | No hard blocker found in a full verification pass; real ceilings are resolution/precision, not access |
| Betterment over existing systems | 6/10 | Real, narrow, defensible gains in spatial resolution and alert-relay speed — not a claim of superior forecasting science |
| SIH prototype/demo feasibility | 8.5/10 | Achievable end-to-end if LOEO and rehearsal time are protected above all else |

---

## 20. Demo Script (rehearse exactly)

One village, one escalating event, ~3 minutes live. All numbers below are illustrative —
replace with real model output on rehearsal.

| Stage | Trigger | Risk | Tier | Confidence | Dashboard shows |
|---|---|---|---|---|---|
| 1. Normal | baseline | 21 | Green | 91 | 1D trend line only |
| 2. Rainfall rising | synthetic rain spike begins | 48 | Yellow | 84 | trend line updates live |
| 3. Saturation building | soil moisture + antecedent rain both high | 67 | Orange | 76 | 2D simplified inundation raster triggers |
| 4. Slope response | FS drops below 1.0 for adjacent hexes (band 0.7–1.1) | 82 | Red | 88 | feature-contribution panel + **lead time: 120 min (t+2h forecast crossing)** |
| 5. Decision | — | — | — | — | tier, score, confidence, lead time, nearest static shelter + CAP alert fires on screen |

> Stage 4's lead-time example is updated to hour-granularity per Section 12's frozen decision.

Close with: "This is a real, valid CAP message — the exact format Sachet ingests. We removed
the manual forecaster-relay step that exists today. The lead time and confidence score are
computed, not hand-set. The shelter recommendation is a static lookup for this demo region —
full exposure-aware routing is Phase 2, not something we're claiming to have built." Say that
last sentence before a judge asks it.

---

## 21. Team Roles (6 people, 3 days / ~72 hours)

| Role | Owns |
|---|---|
| A — Geo/Physics | DEM, H3 grid, FS model + uncertainty band, manual GSI susceptibility digitization for the pilot hexes |
| B — Data/ML | Historical event compilation, event-centered temporal sampling with tier labels (Section 11.2), feature engineering, fusion model training |
| F — Validation | LOEO harness, built in parallel with B, not after |
| C — Backend | FastAPI, PostGIS, all endpoints, forecast-based lead-time, live/demo fallback, CAP generator with dedup/downgrade logic |
| D — IoT/Simulation | MQTT publisher, scripted escalation curve, sensor-health fallback |
| E — Frontend | Dashboard, heatmap, feature-contribution panel, confidence/lead-time display, validation panel, live/cached-demo label |

**Hard cuts, no debate:** XGBoost only (no PSO-BP), one pilot cluster only, no
exposure/routing layer, no live GSI/SAsiaFFGS integration, no SMAP, Leaflet only (no Mapbox),
pysheds only (no whitebox/richdem).

**Checkpoints that gate everything downstream — protect these above all else:**
- Hour ~6: data pipeline live (rainfall, DEM, POWER, ESA WorldCover pulling; GSI class
  digitized)
- Hour ~30: LOEO validation has run and produced numbers (even mediocre ones — report
  honestly)
- Hour ~44: full 5-stage escalation demo runs end-to-end without breaking
- After hour ~50: no new features — rehearsal and judge Q&A memorization only

---

## 22. Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Small historical event set (~30–50) | High | Event-centered sampling for training signal; report event-level count honestly as validation size |
| Imprecise event coordinates from news sources | High | Tagged `coordinate_precision` field (Section 11.3); disclose the LOEO timing-error spread honestly |
| No live SAsiaFFGS/GSI integration | High | Labeled proxies + upstream-adapter framing (Section 2); scripted judge answer (Section 23) |
| Coarse soil-moisture resolution (~50km) | Medium | Labeled "soil saturation proxy" (Section 10.1), never village-resolution ground truth |
| Forecast-dependent lead time | Medium | Hourly-only horizons (Section 12); show which horizon triggered the crossing, report LOEO timing error alongside it |
| GSI susceptibility digitization slips | Medium | Bounded manual task, scheduled owner + hour slot (Section 21) |
| Live demo API failure | Medium | Live/cached-demo fallback (Section 13), visible on dashboard |
| 6-person execution scope creep | High | CLAUDE.md hard constraints (Section 26); no new features after hour ~50 |
| Wayanad-only scope | Low | Region-agnostic pipeline framing — regional layers swap, core engine doesn't |
| Duplicate/repeated alerts flooding the demo | Medium | Dedup + cooldown logic (Section 17.1) |
| Alert flapping on tier noise near a boundary | Medium | 2-cycle persistence requirement before downgrade (Section 17.2) |

---

## 23. One-Sentence Answers to Likely Judge Questions

- **"How is this different from what IMD already does?"** → village-resolution downscaling,
  physics-coupled landslide model with an uncertainty band, algorithmic lead time,
  direct-to-Sachet push — all specific to SAsiaFFGS's/GSI's documented gaps (Section 2).
- **"Why do you mention GSI — I thought this was a flash-flood system?"** → "Flash floods and
  landslides share the same rainfall-and-slope-saturation physics in hill terrain; SAsiaFFGS
  covers the flood side, GSI's rainfall-threshold approach covers the landslide side, and we
  downscale both with the same physics-coupled model."
- **"Are you actually integrated with SAsiaFFGS?"** → "Not in the prototype — we don't claim
  unauthorized machine-readable access. We built an upstream adapter and reproduce the
  relevant signal as a clearly labeled proxy; the downscaling engine itself is real and
  independent of that proxy."
- **"Why only 30–50 events?"** → "The independent validation unit is the historical event, not
  every timestep. We use event-centered temporal samples for training but evaluate with
  event-level leave-one-event-out validation, and we report the actual event count as our
  sample size."
- **"How do you know your lead-time number is real?"** → "It's computed by rerunning our
  LOEO-validated model against Open-Meteo's hourly forecast rainfall at successive horizons
  and finding the first Red crossing — not hand-set."
- **"What does the confidence score mean?"** → "It blends Factor-of-Safety uncertainty with
  how decisively the model places a prediction away from a tier boundary. It's a confidence
  index, not a calibrated probability."
- **"Does this work outside Wayanad?"** → "Wayanad is our validated pilot; the pipeline is
  region-agnostic — deploying elsewhere means replacing the regional terrain, susceptibility,
  event, and geotechnical layers, not rewriting the core engine."
- **"What happens if a sensor fails / the forecast is wrong?"** → live-demo the fallback
  (Section 16) and state the LOEO timing-error spread honestly rather than a single best-case
  number.
- **"How did you compute the shelter recommendation?"** → "A static, hand-entered lookup of
  known Wayanad shelter locations for this demo region — not live routing. Full
  exposure-aware routing is Phase 2." Say this proactively in the demo close (Section 20).
- **"Why isn't your soil moisture more precise?"** → "NASA POWER's native resolution is ~50km;
  we're upfront that this is a saturation proxy assigned to each hex, not an independent
  hex-level measurement — that's a real, disclosed ceiling, not something we're hiding."

---

## 24. What NOT to Build

- Full LoRaWAN hardware deployment
- Real-time LLM-based national news mining pipeline
- Full hydrodynamic (SCHISM-class) inundation modeling
- Exposure/impact engine: population weighting, school/hospital/road exposure, live
  safe-routing
- A live-recomputed LOEO validator
- Real GSI RLFS / SAsiaFFGS API integration
- District- or state-wide coverage
- NASA SMAP integration
- Time spent hunting for a GSI bulk-inventory export that may not exist
- PSO-BP, in any form, for any reason
- Mapbox, whitebox, or richdem — the stack is frozen (Section 7)

---

## 25. Development Phases — Execute One by One

Each phase below is self-contained: goal, owner, dependencies, acceptance criteria, and a
ready-to-paste prompt for Claude Code or Antigravity. Paste the prompt as-is into a session
that has this file (`SRS.md`) and `CLAUDE.md` (Phase 0 output) available in the repo — every
prompt assumes the assistant can read both.

### Phase 0 — Repository, Environment, and Hard Constraints

**Owner:** whole team, hour 0 · **Depends on:** nothing · **Deliverable:** a repo with
`CLAUDE.md`, folder structure, and environment scaffolding for all 6 roles to branch from.

**Acceptance criteria:** repo exists with `/backend`, `/frontend`, `/ml`, `/iot`, `/data`,
`/docs` folders; `CLAUDE.md` committed at root; each team member can clone and run a "hello
world" in their own stack without conflicts.

**PROMPT — Phase 0**
```
You have access to SRS.md (this document) in the repo. Read Sections 6, 7, 21, and 24 before
doing anything.

Task: scaffold a monorepo for a 6-person hackathon build with this structure:
  /backend   (FastAPI + PostGIS, Python)
  /frontend  (React + Leaflet)
  /ml        (feature engineering, FS model, XGBoost training, LOEO harness — Python)
  /iot       (MQTT simulator — Python)
  /data      (raw and processed data files, gitignored appropriately for large files)
  /docs      (this SRS, plus any generated docs)

Create a CLAUDE.md at the repo root containing these hard constraints, verbatim, for every
future session to inherit:
- Pilot scope: Wayanad only, 4 named villages (Mundakkai, Chooralmala, Attamala,
  Punjirimattom), H3 resolution 8-9. The hex count is whatever the grid generator produces
  for those 4 village polygons — never hardcode "4 hexes." Never expand scope to another
  region without explicit team sign-off.
- Model: XGBoost only. Never suggest or implement PSO-BP.
- Frontend map: Leaflet only. Terrain library: pysheds only. No alternatives.
- Never build: exposure/population/routing layer, real GSI/SAsiaFFGS API integration, NASA
  SMAP integration, district/state-wide coverage, a live-recomputed LOEO validator.
- Soil moisture: NASA POWER only. soil_saturation_ratio = GWETROOT directly (no derived
  formula). Always labeled "soil saturation proxy" in the UI.
- Feature naming: use antecedent_precipitation_index, never api_score.
- risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88, from XGBoost's
  predict_proba. Tier is derived from risk_score via the Section 10.4 thresholds.
- Lead-time horizons are hourly only (t+1h, t+2h, ...) — never sub-hour interpolation.
- Alert dedup: only fire a new CAP alert on tier increase past the last alert, or after a
  30-minute cooldown at the same tier. Tier drops log a "downgrade," never a new alert, and
  require 2 consecutive below-Orange cycles before marking "resolved."
- Any external API call needs a timeout + fallback, and the fallback must be visibly labeled
  in code comments and (where user-facing) in the UI — never a silent mock standing in for
  real data.
- Schema (SRS.md Section 14) and API contracts (SRS.md Section 15) are frozen — do not alter
  field names or add/remove tables without flagging it clearly for team review first.
- SRS.md is the single source of truth. If any other document or chat history conflicts with
  it, SRS.md wins.

Also scaffold minimal environment files (requirements.txt for Python components, package.json
for the frontend) with the dependencies named in SRS.md Section 7 — do not add dependencies
beyond what that section lists without a stated reason.

Do not implement any feature logic yet — this phase is scaffolding and constraints only.
```

### Phase 1 — Data Ingestion Pipeline

**Owner:** C (Backend) + F (Validation), supported by A for the DEM pull · **Depends on:**
Phase 0 · **Deliverable:** working scripts that pull rainfall (current + forecast), DEM, soil
moisture, and land cover into `/data`, ready for feature engineering.

**Acceptance criteria:** each script runs standalone and produces a saved file
(CSV/GeoTIFF/Parquet) for the Wayanad pilot cluster bounding box; no manual/interactive steps
required at runtime.

**PROMPT — Phase 1**
```
Read SRS.md Sections 5, 8, and 13 before starting.

Task: implement data ingestion scripts under /data/scripts/ for the Wayanad pilot cluster
(Mundakkai, Chooralmala, Attamala, Punjirimattom — get approximate bounding-box coordinates
for this area):

1. ingest_rainfall.py — pull current + hourly forecast rainfall from the Open-Meteo API (no
   key required) for the pilot bounding box. Save both series to /data/weather/.
2. ingest_dem.py — pull SRTM 30m DEM tiles covering the pilot bounding box via the
   OpenTopography API (requires an API key — read it from an environment variable, do not
   hardcode it). Save as GeoTIFF to /data/terrain/.
3. ingest_soil.py — pull NASA POWER soil-moisture data (the GWETROOT parameter specifically)
   for the pilot bounding box (no key required). Save to /data/soil/. Add a code comment
   noting the ~50km native resolution as a known limitation, per SRS.md Section 8, and that
   GWETROOT is used directly as soil_saturation_ratio per Section 10.1.
4. ingest_landcover.py — pull the relevant ESA WorldCover 10m tile(s) covering the pilot
   bounding box from the public S3 bucket, plus the corresponding NDVI percentile composite.
   Save both to /data/landcover/.

Each script must:
- Run standalone with no interactive prompts.
- Fail loudly with a clear error message if a source is unreachable — do not silently
  substitute fake data (per CLAUDE.md).
- Include a short docstring citing which SRS.md section it implements.

Do not implement the GSI susceptibility digitization here — that's a manual task, Phase 2.
```

### Phase 2 — GSI Susceptibility Digitization (manual + encoding script)

**Owner:** A · **Depends on:** Phase 0 (can run in parallel with Phase 1) · **Deliverable:** a
small CSV/table mapping each pilot hex to a susceptibility class, manually read off the GSI
Bhukosh viewer, plus a script to load it into the schema.

**Acceptance criteria:** `gsi_susceptibility.csv` exists with one row per pilot hex; a script
loads it into the `hexes.static_features` JSONB field without errors.

**PROMPT — Phase 2**
```
Read SRS.md Section 8's row on gsi_susceptibility_class before starting.

Context: I have manually read the GSI susceptibility class for the pilot hexes covering
Mundakkai, Chooralmala, Attamala, and Punjirimattom off the Bhukosh/NGDR map viewer, since no
bulk API exists for this. Per SRS.md Section 5, this is 4 villages' worth of H3 res 8-9 hexes
— not exactly 4 hexes. I will provide you the hex-to-class mapping.

Task:
1. Create /data/susceptibility/gsi_susceptibility.csv with columns: hex_id, susceptibility_class
   (values I'll provide, e.g. Low/Moderate/High/Very High).
2. Write a script load_gsi_susceptibility.py that reads this CSV, generates H3 hex IDs for the
   pilot cluster at resolution 8-9 covering each named village polygon, and writes the
   susceptibility class into each hex's static_features JSONB in the hexes table (per SRS.md
   Section 14 schema).

Do not attempt to scrape or programmatically query the Bhukosh portal — this is explicitly a
manual, hand-entered value per SRS.md Section 8. Do not assume exactly 4 rows in the CSV —
the row count is whatever the grid produces for the 4 villages.
```

### Phase 3 — Static Feature Engineering (Susceptibility Layer)

**Owner:** A · **Depends on:** Phases 1 and 2 · **Deliverable:** all 11 static features
computed per hex and written to `hexes.static_features`.

**Acceptance criteria:** querying `hexes` for any pilot hex returns all 11 static features
listed in SRS.md Section 9, with plausible (non-null, non-placeholder) values.

**PROMPT — Phase 3**
```
Read SRS.md Sections 6, 9, and 14 before starting.

Task: implement /ml/features/static_features.py which, given the DEM GeoTIFF (from Phase 1)
and the H3 hex grid (resolution 8-9) for the pilot cluster:

1. Computes slope_deg, aspect, elevation directly from the DEM per hex (use rasterio + numpy,
   or an equivalent library).
2. Computes TWI and TRI using flow-accumulation-based methods, using pysheds (frozen choice,
   SRS.md Section 7/20 — do not substitute whitebox or richdem).
3. Derives a stream network from the DEM (flow-accumulation threshold) and computes
   distance_to_stream_m and drainage_density per hex.
4. Reads land_use_class and ndvi_mean from the ESA WorldCover / NDVI tiles pulled in Phase 1,
   sampled per hex.
5. Reads gsi_susceptibility_class from the table populated in Phase 2.
6. Computes historical_event_count_500m as a placeholder function for now (it depends on the
   historical event compilation from Phase 4 — leave a clear TODO and a function signature
   that Phase 4's output can plug into).
7. Writes all 11 features into hexes.static_features as JSONB, matching the schema in SRS.md
   Section 14 exactly — do not rename or restructure fields.

Print a summary table of all 11 features for each pilot hex at the end, so the values can be
sanity-checked before moving on.
```

### Phase 4 — Historical Event Compilation & Event-Centered Sampling

**Owner:** B · **Depends on:** Phase 0 (can start immediately, in parallel with Phases 1–3) ·
**Deliverable:** a compiled event spreadsheet (~30–50 events) and an event-centered
time-stepped sample set for training, with the frozen label scheme applied.

**Acceptance criteria:** `historical_events` table populated with real, sourced events,
including `coordinate_precision`; `event_centered_samples.parquet` exists with 72h/48h/24h/
12h/6h-before samples per event, each carrying its escalating tier label and traceable back
to its parent event.

**PROMPT — Phase 4**
```
Read SRS.md Sections 11 and 18 before starting.

Context: I am manually compiling 30-50 historical flood/landslide events for Wayanad,
cross-referencing public news coverage and the research papers cited in SRS.md Section 18
(especially the Mundakkai-Chooralmala Scientific Reports and Landslides journal papers, which
document the July 2024 event in detail). I will provide the compiled list, including whether
each event's location is village-level or point-level precision.

Task:
1. Create /data/events/historical_events.csv with columns matching the historical_events
   schema in SRS.md Section 14: event_id, hex_id, date, type, severity, source,
   coordinate_precision. If coordinate_precision is "village-level", the event applies to ALL
   hexes covering that village polygon, per SRS.md Section 11.3. Load it into the
   historical_events table.
2. Implement /ml/features/event_centered_sampling.py which, for each event, generates
   time-stepped feature samples at 72h, 48h, 24h, 12h, and 6h before the recorded event time,
   using the actual observed rainfall/soil trajectory from the ingested data (Phase 1) for
   that hex leading up to the event. Apply the escalating tier label scheme from SRS.md
   Section 11.2 (72h/48h -> Yellow, 24h/12h -> Orange, 6h/event -> Red) to each sample. Each
   generated sample must retain a reference to its parent event_id.
3. Also generate negative samples per SRS.md Section 11.4: a 4:1 negative:positive ratio,
   drawn from (a) the same pilot hexes on dates >=30 days from any event, and (b) other pilot
   hexes during a real storm period with no reported failure. Exclude any timestep within 7
   days of a labeled positive event from the negative pool. All negatives get tier: Green.
4. Output the combined positive + negative sample set to
   /data/events/event_centered_samples.parquet.
5. Add a clear code comment stating: these samples increase training signal only — the
   validation unit for LOEO (Phase 7) remains the event, not the timestep, per SRS.md Section
   11.

Do not conflate the timestep count with the event count anywhere in logging, output, or
comments — always report the event count (~30-50) as the sample size for validation purposes.
```

### Phase 5 — Factor of Safety Model + Uncertainty Band

**Owner:** A · **Depends on:** Phase 3 (needs slope, DEM-derived features) and soil data
(Phase 1) · **Deliverable:** `factor_of_safety`, `factor_of_safety_min`,
`factor_of_safety_max` computed per hex per cycle.

**Acceptance criteria:** for a sample hex with known-ish conditions, the computed FS values
are physically plausible (roughly 0.5–2.0 range) and min ≤ mid ≤ max holds for every hex.

**PROMPT — Phase 5**
```
Read SRS.md Section 10.1 carefully before starting — the exact equation and parameter
sourcing matter here.

Task: implement /ml/models/factor_of_safety.py with this exact infinite-slope equation:

FS = [c' + (gamma - gamma_w * m) * z * cos(beta)^2 * tan(phi')] / [gamma * z * sin(beta) * cos(beta)]

where:
- beta = slope angle in radians (from the slope_deg static feature, converted)
- m = saturation ratio, 0-1 = soil_saturation_ratio = GWETROOT directly, per SRS.md Section
  10.1's frozen formula — no derivation needed, use the ingested NASA POWER value as-is
- c', phi', z, gamma = soil cohesion, friction angle, depth, unit weight

I will provide you the site-specific parameter values from the Mundakkai-Chooralmala
Scientific Reports paper (SRS.md Section 18, reference 1) for cohesion and friction angle,
plus a supplementary min/max range from published Kerala laterite literature for any gaps.

The function must:
1. Compute a single mid-estimate FS using the paper's central parameter values.
2. Compute factor_of_safety_min using the worst-case combination (lowest cohesion, lowest
   friction angle, highest unit weight from the provided range).
3. Compute factor_of_safety_max using the best-case combination.
4. Return all three values per hex per cycle, ready to be written into
   observations.dynamic_features (SRS.md Section 14 schema) alongside the other 13 hazard
   features.

This must be a pure deterministic calculation — no Monte Carlo, no random sampling, per
SRS.md Section 10.1's explicit scope note. Write a short unit test with a hand-computed
example to verify correctness before this feeds into the fusion model.
```

### Phase 6 — Dynamic Feature Engineering & Fusion Model Training

**Owner:** B · **Depends on:** Phases 1, 4, and 5 · **Deliverable:** all 14 dynamic features
computed per cycle; a trained XGBoost model producing `risk_score` (via the frozen formula)
and feature contributions.

**Acceptance criteria:** the model trains without error on the compiled + event-centered
dataset and produces a `risk_score` (0–100) and feature-importance breakdown for a held-out
sample hex-timestep.

**PROMPT — Phase 6**
```
Read SRS.md Sections 9, 10.2, and 10.3 before starting.

Task, part 1 — dynamic features: implement /ml/features/dynamic_features.py computing, per
hex per ingestion cycle, all 14 hazard features listed in SRS.md Section 9: rainfall_1h/3h/
6h/24h, rainfall_72h_antecedent, rain_intensity_mm_hr, antecedent_precipitation_index
(renamed from api_score — do not use the old name anywhere in code), soil_saturation_ratio
(= GWETROOT directly), factor_of_safety/_min/_max (call Phase 5's function),
simulated_ffgs_signal (simple rainfall-threshold rule, clearly labeled as simulated in a code
comment), simulated_gsi_signal (rainfall + gsi_susceptibility_class rule, also labeled
simulated), and iot_anomaly_flag (stub returning False until Phase 10's IoT simulation
exists).

Task, part 2 — fusion model: implement /ml/models/train_fusion_model.py:
1. Load the event-centered sample set (Phase 4, already includes the 4:1 negative sampling)
   joined with static (Phase 3) and dynamic (part 1) features.
2. Train an XGBoost classifier producing class probabilities for each of the 4 tiers.
3. Compute risk_score using SRS.md Section 10.2's frozen formula:
   risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88
   Derive the tier from risk_score using Section 10.4's thresholds — do not use a separate
   argmax-based tier prediction that could disagree with the score.
4. Extract feature importances / per-prediction feature contributions for the explainability
   panel.
5. Implement confidence_score per SRS.md Section 10.3:
   confidence_score = 100 * model_class_probability * (1 - FS_band_width_penalty)
   where model_class_probability is XGBoost's probability for the predicted tier, and
   FS_band_width_penalty is 0 if the FS band doesn't straddle 1.0, rising toward ~0.3 as the
   band widens and straddles it.
6. Save the trained model to /ml/models/fusion_model.pkl (or equivalent) for reuse by the
   LOEO harness (Phase 7) and the lead-time endpoint (Phase 9).

Do not implement PSO-BP under any circumstances — XGBoost only, per CLAUDE.md.
```

### Phase 7 — LOEO Validation

**Owner:** F · **Depends on:** Phase 6 (needs a trained model, even a first-pass one) ·
**Deliverable:** `loeo_results` table populated with detection, false-positive rate, and
timing-error spread across all compiled events.

**Acceptance criteria:** every historical event has a row in `loeo_results`; the aggregate
detection rate, false-positive rate, and timing-error distribution are printed/logged
clearly, including worst-case events, not just best-case ones. This phase gates Phases 9 and
17's numbers — do not let it be skipped or rushed.

**PROMPT — Phase 7**
```
Read SRS.md Section 11 in full before starting — the event-level validation discipline here
is the most important correctness constraint in the whole project.

Task: implement /ml/validation/loeo.py:

For each historical event E in historical_events:
1. Retrain the fusion model (Phase 6's training function) on all OTHER events, explicitly
   excluding E and all of its event-centered timesteps (Phase 4), plus any hex-timesteps
   within a reasonable time window of E's timestamp, to prevent leakage.
2. Run the retrained model forward through E's actual observed rainfall/soil time series, hex
   by hex, timestep by timestep.
3. Determine detection: did the tier cross Orange/Red at any point before or at E's reported
   time, for the affected hex(es)?
4. If detected, compute timing_error_min: the difference between the crossing time and E's
   reported time (use whatever ground-truth precision is actually available — do not
   fabricate minute-level precision the historical record doesn't support).
5. Write one row per event to loeo_results: event_id, detected, crossing_tier,
   timing_error_min, notes.

After processing all events, print/log an aggregate summary:
- Detection rate (recall) across all events
- False-positive rate on the negative (non-event) samples used in training
- Mean AND median timing error, WITH the full spread (min/max), including worst-case events

Do not report only a single accuracy number — SRS.md Section 11 explicitly requires the
fuller breakdown. Do not build this as a live/on-demand re-runner — it runs once (or once per
retrain) and its results are read statically by the /validation/loeo API endpoint (Phase 9).
```

### Phase 8 — Backend API & Database

**Owner:** C · **Depends on:** Phases 3, 5, 6 (needs features and model to serve real data) ·
**Deliverable:** FastAPI app implementing every endpoint in SRS.md Section 15, backed by
PostGIS.

**Acceptance criteria:** every endpoint in Section 15 returns real, non-mocked data for at
least one pilot hex; the schema in Section 14 is implemented exactly, with no renamed or
restructured fields.

**PROMPT — Phase 8**
```
Read SRS.md Sections 14 and 15 in full — implement the schema and API contracts exactly as
specified, no renaming or restructuring without flagging it first.

Task: implement the FastAPI backend under /backend/:

1. Set up PostGIS with the exact schema from SRS.md Section 14: hexes, observations,
   risk_scores, historical_events, loeo_results, alerts, alert_state, shelters.
2. Implement all ingestion endpoints: POST /ingest/rainfall, /ingest/rainfall_forecast,
   /ingest/soil_moisture, /ingest/iot.
3. Implement all read endpoints: GET /risk/{hex_id}, /risk/map, /risk/{hex_id}/history,
   /risk/{hex_id}/inundation (gate this IN CODE behind tier >= Orange, not just in the
   frontend), /risk/{hex_id}/uncertainty, /validation/loeo (read statically from
   loeo_results, populated by Phase 7), /shelters/nearest/{hex_id} (simple distance-sort
   against the static shelters table, NOT a routing engine).
4. Wire the risk-computation loop: on each ingestion cycle, join static + dynamic features
   per hex, call the trained fusion model (Phase 6) and FS model (Phase 5), write the result
   to risk_scores.
5. GET /risk/{hex_id} must include a data_source field ("live" | "cached_demo") — the actual
   fallback logic for this is Phase 9's job, but the field needs to exist in the response
   schema now.

Do not implement /alert/trigger or /alert/feed yet — that's Phase 11. Do not implement the
lead-time computation yet — that's Phase 9.
```

### Phase 9 — Lead-Time Endpoint & Live/Demo Fallback

**Owner:** C · **Depends on:** Phase 7 (LOEO must exist first, per the precondition) and
Phase 8 · **Deliverable:** algorithmic, hourly-only lead-time computation wired into GET
`/risk/{hex_id}`; live/cached-demo fallback wired into the Open-Meteo ingestion call.

**Acceptance criteria:** for a hex below Red, the endpoint returns either a real hourly
forecast-horizon crossing time or "no_red_crossing_in_forecast_window" — never a hardcoded or
sub-hour-interpolated number. A forced network failure demonstrably falls through to cached
data without a visible error.

**PROMPT — Phase 9**
```
Read SRS.md Sections 12 and 13 before starting. Confirm the LOEO validation (Phase 7) has
produced results before implementing this — the lead-time number is only meaningful once the
underlying model has been validated.

Task, part 1 — lead time: implement the forecast-based lead-time computation described in
SRS.md Section 12:
1. Pull Open-Meteo's hourly forecast rainfall series for the hex's location.
2. At each hourly forecast horizon (t+1h, t+2h, ... up to the prediction horizon), recompute
   the rainfall-dependent dynamic features (Phase 6, part 1) using forecast rainfall instead
   of observed, and rerun the trained fusion model (Phase 6). Do NOT interpolate sub-hour
   horizons — SRS.md Section 12 explicitly freezes this to hourly steps only.
3. Set lead_time_min to the first hourly horizon (expressed in minutes) where the projected
   tier reaches Red. If none does, set lead_time_basis to
   "no_red_crossing_in_forecast_window" and lead_time_min to null — do not fabricate a
   number.
4. Wire this into GET /risk/{hex_id} (Phase 8), replacing any placeholder value.

Task, part 2 — live/demo fallback: implement the fallback described in SRS.md Section 13:
1. Pre-fetch and cache a full rainfall + forecast snapshot for the pilot cluster now, stored
   in /data/weather/cached_demo_snapshot.json.
2. Wrap the live Open-Meteo call with a 3-5 second timeout; on timeout or error, fall through
   automatically to the cached snapshot, with no manual intervention required.
3. Set the data_source field on GET /risk/{hex_id} responses to "live" or "cached_demo"
   accordingly.

Test part 2 by deliberately blocking network access to Open-Meteo and confirming the
endpoint still returns a valid response with data_source = "cached_demo".
```

### Phase 10 — IoT Simulation

**Owner:** D · **Depends on:** Phase 0 (can run in parallel with most other phases) ·
**Deliverable:** MQTT publisher replaying a scripted escalation curve, with a sensor-dropout
fallback moment.

**Acceptance criteria:** the backend's ingestion endpoint receives simulated sensor messages
and the `iot_anomaly_flag` feature responds accordingly; one sensor visibly "goes offline"
mid-run and the system falls back cleanly, displaying the "external-data-only estimate" label.

**PROMPT — Phase 10**
```
Read SRS.md Section 16 before starting.

Task: implement /iot/simulator.py:
1. Publish synthetic MQTT messages on topics sensors/{hex_id}/rainfall,
   sensors/{hex_id}/soil_moisture, sensors/{hex_id}/tilt, for the pilot hexes.
2. Replay a SCRIPTED escalation curve (matching the 5-stage demo script in SRS.md Section
   20 — Normal -> Rainfall rising -> Saturation building -> Slope response -> Decision)
   rather than random noise, so the demo is reproducible and rehearsable.
3. At a scripted point mid-run, simulate one sensor going offline (stop publishing for that
   device_id) and confirm the backend's ingestion (Phase 8's POST /ingest/iot) and feature
   computation (Phase 6) fall back to the "external-data-only estimate" label for that hex,
   per SRS.md Section 16's frozen wording (not "NWP/satellite-only").
4. Wire published messages into the backend's POST /ingest/iot endpoint (Phase 8).

Do not attempt any real hardware or LoRaWAN integration — this is a pure software simulation,
per CLAUDE.md.
```

### Phase 11 — CAP Alert Generation, Dedup & Downgrade

**Owner:** C · **Depends on:** Phase 8 · **Deliverable:** `POST /alert/trigger` auto-fires on
Orange/Red crossing (respecting dedup rules), generates valid CAP 1.2 XML, logs to the
`alerts` table, and correctly handles downgrades via `alert_state`.

**Acceptance criteria:** a forced Red-tier risk score results in a well-formed CAP XML alert
matching SRS.md Section 17's structure, logged to `alerts`, and visible via `GET
/alert/feed`. A repeated Red-tier score for the same hex within 30 minutes does NOT fire a
second alert. A tier drop is logged as a downgrade, not a new alert, and only marks
"resolved" after 2 consecutive below-Orange cycles.

**PROMPT — Phase 11**
```
Read SRS.md Section 17 in full before starting — match the CAP 1.2 XML structure and the
dedup/downgrade logic exactly.

Task: implement the alert pipeline in /backend/:
1. POST /alert/trigger — internal endpoint, auto-called whenever a risk_scores write results
   in tier = Orange or Red for a hex. Before generating a CAP alert, check the alert_state
   table (SRS.md Section 14): only proceed if the new tier is HIGHER than
   alert_state.last_alert_tier for this hex, OR at least 30 minutes have passed since
   alert_state.last_alert_timestamp. Otherwise, skip alert generation (dedup).
2. On a tier drop below Orange, increment
   alert_state.consecutive_below_orange_cycles; do NOT call the CAP generator. When this
   counter reaches 2, log a "downgrade" event to the dashboard/alert feed (a distinct,
   non-urgent entry, not a CAP alert). Reset the counter to 0 on any cycle where the tier is
   Orange or Red again.
3. When an alert does fire, generate a CAP 1.2 XML payload matching SRS.md Section 17.3's
   example structure, populated with the actual risk_score, tier, confidence_score,
   lead_time_min (hour-granular, per Section 12), and the nearest static shelter (from GET
   /shelters/nearest/{hex_id}, Phase 8). Update alert_state.last_alert_tier and
   last_alert_timestamp.
4. Log the generated alert to the alerts table (SRS.md Section 14 schema): alert_id, hex_id,
   timestamp, tier, cap_payload JSONB, delivered_channels TEXT[].
5. Route the alert to: a mock "Sachet-compatible" webhook (a stub endpoint that just logs
   receipt), a simulated SMS log (a text file or table row), and the dashboard alert feed.
6. Implement GET /alert/feed returning the list of active alerts AND downgrade events for
   frontend consumption.

Do not attempt to integrate with a real Sachet endpoint — none exists publicly, per SRS.md
Section 8. The mock webhook is the correct and final implementation for this build, not a
placeholder for something more you'll build later.
```

### Phase 12 — Frontend Dashboard

**Owner:** E · **Depends on:** Phase 8 (needs live endpoints to connect to) · **Deliverable:**
a working React dashboard with hex heatmap, trend view, feature-contribution panel,
confidence/lead-time display, validation panel, and the live/cached-demo label.

**Acceptance criteria:** loading the dashboard against the running backend shows real risk
data for the pilot cluster, updates live as the IoT simulation runs, and visibly displays
which data source (live/cached) is active.

**PROMPT — Phase 12**
```
Read SRS.md Sections 15 and 20 before starting.

Task: implement the React frontend under /frontend/:
1. A Leaflet map (frozen choice, SRS.md Section 7 — do not use Mapbox) showing the pilot
   hexes as a hex-colored heatmap, colored by tier (Green/Yellow/Orange/Red), pulling from
   GET /risk/map.
2. A 1D trend line view per hex, pulling from GET /risk/{hex_id}/history.
3. A simplified 2D inundation view that only renders when a hex's tier >= Orange, pulling
   from GET /risk/{hex_id}/inundation.
4. A feature-contribution panel showing the top contributing features for a selected hex's
   current risk score, from GET /risk/{hex_id}.
5. A confidence + lead-time display showing confidence_score, lead_time_min (hour-granular),
   and lead_time_basis (showing the honest "no_red_crossing_in_forecast_window" state when
   applicable) from the same endpoint.
6. A validation-results panel reading from GET /validation/loeo, showing detection rate,
   false-positive rate, and timing-error spread — present this as a static "how we validated
   this" panel, not a live-updating one.
7. An alert feed panel pulling from GET /alert/feed, showing fired CAP alerts AND downgrade
   events distinctly (per Phase 11).
8. A small, always-visible "Data source: LIVE" / "Data source: CACHED DEMO" label reading the
   data_source field from GET /risk/{hex_id} responses, per SRS.md Section 13.
9. Where a hex's IoT sensor is offline, show the "external-data-only estimate" label per
   SRS.md Section 16 — never "satellite-only."

Match the visual escalation described in SRS.md Section 20's demo script table so the
dashboard tells a coherent story as the IoT simulation (Phase 10) runs through its scripted
curve.
```

### Phase 13 — Integration & Demo Rehearsal

**Owner:** whole team · **Depends on:** all previous phases · **Deliverable:** a working
end-to-end run of the full 5-stage demo script, rehearsed and timed.

**Acceptance criteria:** running the IoT simulator against the live backend and frontend
reproduces SRS.md Section 20's 5-stage escalation exactly, including a CAP alert firing on
screen with the correct hour-granular lead time, with no manual intervention required during
the run.

**PROMPT — Phase 13**
```
Read SRS.md Section 20 in full.

Task: write an integration test / run script (/scripts/run_demo.sh or equivalent) that:
1. Starts the backend (Phase 8/9/11), the IoT simulator (Phase 10) in scripted-escalation
   mode, and confirms the frontend (Phase 12) is pointed at the running backend.
2. Runs through all 5 stages of SRS.md Section 20's demo script without manual intervention,
   verifying at each stage that: the risk score, tier, and confidence shown on the dashboard
   match what the backend computed (not hardcoded); the CAP alert fires automatically at the
   Red-tier stage with an hour-granular lead time; the data-source label and validation panel
   are visibly correct throughout; a repeated Red score does not fire a duplicate alert.
3. Logs a clear pass/fail summary for each of the 5 stages so the team can quickly spot which
   component broke if the run doesn't complete cleanly.

After this passes once, the team's remaining time should go entirely into REHEARSING the live
narration alongside this run (per SRS.md Section 20's closing statement and Section 23's judge
Q&A) — do not add new features once this integration test passes reliably.
```

---

## 26. CLAUDE.md — Hard Constraints (append verbatim to repo-root CLAUDE.md)

```
- Pilot scope: Wayanad only, 4 named villages (Mundakkai, Chooralmala, Attamala,
  Punjirimattom), H3 resolution 8-9. Hex count is whatever the grid generator produces for
  those 4 villages — never hardcode "4 hexes." Never expand scope to another region without
  explicit team sign-off.
- Model: XGBoost only. Never suggest or implement PSO-BP, under any circumstances.
- Frontend map: Leaflet only. Terrain library: pysheds only. No alternatives, no debate.
- Never build: exposure/population/routing layer, real GSI/SAsiaFFGS API integration, NASA
  SMAP integration, district/state-wide coverage, a live-recomputed LOEO validator.
- Soil moisture: NASA POWER only. soil_saturation_ratio = GWETROOT directly.
- Feature naming: antecedent_precipitation_index, never api_score.
- risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88 (from XGBoost
  predict_proba); tier is derived from risk_score, never predicted separately.
- Lead-time horizons: hourly only (t+1h, t+2h, ...). Never sub-hour interpolation.
- Alert dedup: fire only on tier increase past the last alert, or after a 30-min cooldown at
  the same tier. Downgrades log an event, never a new alert, and require 2 consecutive
  below-Orange cycles before "resolved."
- Any external API call needs a timeout + fallback, visibly labeled in code and (where
  user-facing) in the UI — never a silent mock standing in for real data.
- Wording: "soil saturation proxy" (never "village-level measurement"), "external-data-only
  estimate" (never "satellite-only").
- Schema (Section 14) and API contracts (Section 15) are frozen — do not alter field names or
  add/remove tables without flagging it for team review first.
- SRS.md is the single source of truth. If any other document or chat history conflicts with
  it, SRS.md wins and the other document should be corrected to match.
```

---

*End of document. This SRS (v2.0) supersedes v1.0 and all prior conversational planning as
the single reference. Every ambiguity flagged in the v1.0 QA review has been resolved above —
no open items remain. If a future prompt or judge question surfaces something this document
doesn't cover, update this file directly rather than letting the answer live only in chat
history.*
