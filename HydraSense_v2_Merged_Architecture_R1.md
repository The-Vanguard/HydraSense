# HydraSense v2 — Multi-Mechanism, Confidence-Aware Early Warning for Hilly India

**Subtitle:** Region-agnostic flash-flood and landslide early warning at village/ward level, with sensor-snapping where sensors exist and honest uncertainty where they don't
**Prepared for:** Smart India Hackathon — *Flash Flood Prediction System for Hilly Regions using Multi-Source Data*
**Status:** Merged architecture. Combines HydraSense (Final) with the mechanism-aware, sensor-first design, and applies all 32 fixes listed in Appendix A. Revision R1 (Appendix F) adds village-level reporting rules, multi-region validation, a region-agnostic replay pilot, a simulated live-operations demo, and sensor and laterite-physics hardening.

> **Reading guide.** Section 1 is a self-contained summary. Sections 4–12 define the system. Section 15 defines how it is proven. Appendix E lists every number that this document deliberately does **not** state because it must come from running the system (event counts, back-test results, fitted constants, quotes).

## Contents

1. Executive summary
2. Problem-statement coverage
3. Positioning and scope
4. System architecture overview
5. Autonomous Region Onboarding (with catchments, villages, sensor siting)
6. Data layer
7. Hazard engines
8. ML fusion layer
9. Decision engine
10. Alerting and governance
11. Exposure, priority and evacuation
12. IoT and edge layer
13. Dashboard and user experience
14. Backend, API and stack
15. Validation and evidence plan
16. Demo plan and fallback strategy
17. Build plan and MVP scope
18. Limitations
19. Roadmap
- Appendix A — Fix traceability
- Appendix B — CAP example
- Appendix C — Design FAQ
- Appendix D — 10-slide pitch outline
- Appendix E — Open items that need real numbers
- Appendix F — Revision log (R1)

---

## 1. Executive summary

Hilly India loses lives to flash floods and rainfall-triggered landslides that arrive with little warning. National systems each cover a slice: SAsiaFFGS gives 4 km flash-flood guidance, GSI's forecasting is district-scale and covers a limited set of mapped districts, CWC watches named river gauges. None resolves risk to the village or ward, fuses flood and landslide on shared physical drivers, and works for terrain that has never been pre-mapped or instrumented.

**HydraSense v2** is a decision layer that does exactly that, in four moves:

1. **Resolve any hilly place automatically.** A place name or drawn boundary becomes terrain, land cover, soil-derived geotechnical parameters, micro-catchments, H3 hexes and village/ward polygons, with no manual per-region configuration.
2. **Model the mechanism, not just the score.** A physics slope-stability engine (with uncertainty), a micro-catchment runoff engine, and a stream-blockage check feed two learned hazard heads (flood, landslide). A rule-based trigger classifier names the dominant mechanism — cloudburst flash flood, saturation flood, saturation landslide, landslide-dam — so the alert says what to do and how much lead time is realistic.
3. **Snap to sensors, degrade honestly.** Where a local rain/soil-moisture/level node exists, its readings correct the physics and rainfall directly. Where none exists, the system runs on satellite and forecast data and shows, per hex and per village, exactly why its confidence is lower.
4. **Turn risk into governed action.** Village-level tiered alerts in CAP 1.2, held for two-person authorization, with an offline-capable edge tier (siren + SMS) and a static shelter/route advisory.

**One-sentence definition.** HydraSense v2 is a region-agnostic, mechanism-aware flash-flood and landslide decision-support system that downscales national guidance to village/ward-level risk by fusing terrain, rainfall, soil state, physics-based stability, catchment runoff and local sensors with ML, and that reports — per region, per hazard, at prediction time — how much of each estimate is backed by local evidence.

**The claim, stated precisely.** The architecture runs anywhere in hilly India with no manual setup (demonstrable). Empirical accuracy is validated only where event data exists, and the system says so out loud (Section 15 defines the evidence; Appendix E lists what is still to be produced). The no-manual-setup part is demonstrated by a zero-config replay pilot across eleven hilly regions (Section 15.12); accuracy is reported separately per region (Section 15.8).

**What is built vs. simulated vs. future** (full table in Section 17):

| Real in the prototype | Simulated, always labeled | Future scope |
|---|---|---|
| Onboarding, terrain/catchment/village mapping, FS + uncertainty, SCS-CN runoff, two-head model, trigger classifier, confidence, CAP drafting, dashboard, 1–2 edge nodes (or labeled replay) | Most IoT nodes, SAsiaFFGS/GSI operational feeds, SACHET publishing | GLOF module, debris-flow seismic sensing, LSTM nowcasting, full dynamic evacuation routing, exposure calibration |

---

## 2. Problem-statement coverage

| Statement requirement | How v2 satisfies it | Section | Honest status |
|---|---|---|---|
| Rainfall data | Gauge + satellite + NWP merged and terrain-adjusted to ~1 km; antecedent accumulations | 6.3 | Real; gauge access limited |
| Soil moisture sensors | In-situ sensor stream feeds saturation term in FS; satellite/model soil moisture where no sensor | 7.2, 12 | 1–2 real/replayed nodes, rest simulated |
| Slope stability models | Infinite-slope FS with Monte-Carlo uncertainty (soil params **and** depth) | 7.2 | Real, screening-grade |
| Historical landslide inventories | Training labels, I–D threshold fitting, confidence tiering | 7.2, 8, 15 | Real where obtainable |
| Real-time IoT inputs | MQTT ingestion, QC, sensor-snapping, edge thresholds | 12 | Partly simulated |
| Hyper-local, village/ward | Hex + micro-catchment mapped to village/ward polygons; settlement-footprint alerting | 5.3, 10 | Real |
| Actionable lead time | Per-mechanism, hour-resolution ranges with honest "little/no lead time" for cloudbursts | 9.4 | Forecast-limited |
| Early warnings | CAP alerts, authorization gate, offline edge tier | 10, 12 | Publishing needs sponsorship |
| Evacuation and preparedness | Priority ranking, village→shelter advisory, road-blockage flag | 11 | MVP advisory |

---

## 3. Positioning and scope

### 3.1 Relationship with existing Indian systems

*Figures in this table are carried from the earlier HydraSense document and must be re-verified against current sources before submission.*

| System | Hazard | Spatial unit | Lead time | Method | Local sensors | Gap for this statement |
|---|---|---|---|---|---|---|
| SAsiaFFGS (IMD) | Flash flood | ~4 km watershed | 6–24 h | Hydrological guidance | Limited | Too coarse to say which village |
| GSI landslide forecasting | Landslide | District bulletin | Daily | Empirical rainfall thresholds | Limited to pilot sites | District scale, limited mapped coverage, no flood |
| CWC flood forecasting | River flood | Named gauges | Hours | Hydrodynamic routing | Extensive on major rivers | Sparse in small steep catchments |
| C-FLOOD | River flood | Village, in covered basins | ~2 days | Hydrodynamic inundation modelling | Basin gauges | Few large basins, no landslide |
| IMD MHEW-DSS | Generic weather | District/block | Hours–days | Weather-warning decision support | Weather stations | No hydrology or slope physics |
| SACHET | Dissemination | CAP polygons | n/a | Alert dissemination | n/a | Not a predictor; recognized agencies only |
| ISRO/NRSC | Mostly post-event mapping | Scenes/corridors | Mostly reactive | Satellite mapping | n/a | Not forward hyper-local prediction |
| **HydraSense v2** | Coupled flash flood and landslide | Village/ward via H3 and micro-catchments | Hours, per mechanism | Physics-informed ML fusion | Sensor-snapping where nodes exist | This proposal; accuracy validated only where events exist |

*The Method and Local sensors columns are new and need the same re-verification.*

**Positioning.** HydraSense v2 is the missing last-mile layer: it consumes upstream guidance (IMD rainfall, GSI susceptibility where mapped) and can, once sponsored, push village-level CAP output to NDMA/SACHET. It replaces none of them.

### 3.2 What it is not

- Not a hydrodynamic flood simulator; the flood engine is a screening-grade catchment model.
- Not a certified geotechnical assessment; FS is an index with an uncertainty band.
- Not a model of deep-seated or slow-moving slope failures; infinite-slope FS covers shallow, rainfall-triggered translational slides only.
- Not a live integration into IMD/GSI/SACHET feeds; simulated adapters stand in and are labeled.
- Not a claim of uniform accuracy across all hill regions.
- Not an autonomous alert publisher; every Orange/Red alert is drafted and held for human authorization.

### 3.3 Two claims that must never be conflated

| Claim | Achievable? | Basis |
|---|---|---|
| Architecturally region-agnostic (no manual setup, runs anywhere) | Yes | Every input is globally queryable or derived; demonstrated by the multi-region replay pilot with zero manual configuration (Section 15.12) |
| Empirically validated accuracy everywhere in hilly India | No, for any team | Needs labeled event data per region |
| Village-scale rainfall skill | No | Rainfall is a terrain-adjusted ~1 km field; village output is a reporting resolution built on terrain-local physics, with rainfall uncertainty shown |

---

## 4. System architecture overview

```text
┌──────────────────────────── L0  EDGE / FIELD ─────────────────────────────┐
│ Node: rain gauge, soil moisture (2 depths), tilt, stream level, siren      │
│ On-device threshold rule → siren + SMS, no cloud dependency                │
│ LoRa → gateway (GSM) → MQTT        Human relay backstop per village        │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌────────────────────────── L1  DATA SOURCES ────────────────────────────────┐
│ Gauges/AWS | IMERG | NWP/Open-Meteo | DEM | WorldCover | SoilGrids         │
│ ERA5-Land (training only) | GSI/Bhukosh inventory | OSM | WorldPop          │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌───────────────── L2  AUTONOMOUS REGION ONBOARDING (Sec. 5) ────────────────┐
│ boundary → DEM → terrain → catchments → land cover → soil params →          │
│ H3 grid → village/ward polygons → history check → sensor-siting ranking    │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌───────────────── L3  DYNAMIC STATE & DOWNSCALING (Sec. 6) ─────────────────┐
│ QC → gauge-anchored rainfall merge + orographic adjustment (~1 km)          │
│ soil saturation (sensor > model) → antecedent indices → single fallback chain│
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌──────────────────────── L4  HAZARD ENGINES (Sec. 7) ───────────────────────┐
│ E1 static susceptibility  | E2 slope stability (FS + I–D threshold)        │
│ E3 micro-catchment runoff | E4 stream-blockage check (sensor-dependent)     │
│ TC trigger-type classifier (rule-based)                                     │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌─────────────────────── L5  ML FUSION (Sec. 8) ─────────────────────────────┐
│ Flood head + Landslide head (XGBoost), engine outputs as features           │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌──────────────────── L6  DECISION ENGINE (Sec. 9) ───────────────────────────┐
│ risk 0–100 per hazard | tier | 4-factor confidence | lead-time range        │
│ village roll-up | priority = risk × exposure × vulnerability                │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌──────────────── L7  ALERTING & ACTION (Sec. 10–11) ─────────────────────────┐
│ CAP 1.2 draft → two-person authorization → SACHET/CB-ready output           │
│ village names, trigger-specific action text, shelter/route advisory         │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    ▼
┌────────────────── L8  DASHBOARD & FEEDBACK (Sec. 13, 15) ───────────────────┐
│ Decision Authority console | Response Unit view | validation panel          │
│ ground-truth reports → label store → recalibration (frozen per period)      │
└────────────────────────────────────────────────────────────────────────────┘
```

**Design principles**

1. Physics feeds ML; ML never replaces physics.
2. Every number has a defined computation, every source is labeled, every performance claim ties to a validation method.
3. Local truth beats gridded estimates: a healthy sensor overrides the model input at its location.
4. Degradation is always visible: per layer, per hex, per alert.
5. Critical warnings must survive loss of internet (edge tier is standard, not optional).
6. Region-specific parameters are derived by code, never typed in.

---

## 5. Autonomous Region Onboarding

### 5.1 Principle

A region is not configured; it is resolved at request time. The only thing that varies by region is how much historical calibration exists, and that variation is reported, not hidden.

### 5.2 Pipeline

```text
Input: place name OR drawn boundary
   1  Boundary + admin hierarchy (state, district, block, official language)
   2  DEM fetch (Copernicus GLO-30 / SRTM)
   3  Terrain derivatives: slope, aspect, TWI, TRI, HAND, flow accumulation,
      drainage density
   4  Micro-catchment delineation (pour points at stream junctions / settlement
      outlets); per-catchment area, mean slope, main-channel length, Tc inputs
   5  Land cover (ESA WorldCover) → curve number, root-cohesion class
   6  Geotechnical parameters from SoilGrids bulk raster (WCS/GEE):
      γ from bulk density, c' and φ' from texture via pedotransfer,
      soil depth from a global product or a flagged regional default,
      laterite/residual-soil class flag where a geology or soil-class layer exists
   7  H3 grid (resolution chosen from resolved extent; default 8)
   8  Village/ward polygons + settlement footprints (Section 5.3)
   9  Historical-context check: GSI-mapped? usable local event inventory?
        YES → ingest, calibration flag = true
        NO  → flag "no local calibration"; confidence reduced, not hidden
  10  Sensor-siting ranking (Section 12.3)
  11  Output package with per-layer source/quality badges
```

### 5.3 Village and ward mapping

The statement asks for village- or ward-level output. H3 hexes and micro-catchments are computation units, not the reporting unit. Village level is a **reporting resolution**, not a claim of village-scale input skill: only terrain (30 m) and any local sensor are truly village-scale, while rainfall is a terrain-adjusted ~1 km field (Section 6.3).

#### 5.3.1 Boundaries and footprints

| Step | Method |
|---|---|
| Polygons | Tried in order: (1) official village/ward polygons (census or Survey-of-India layers, if accessible), (2) OSM admin boundaries, (3) Voronoi cells around OSM settlement nodes. Each village carries `boundary_quality = official / osm / voronoi_approx` |
| Settlement footprint | Built-up mask from OSM buildings and WorldPop pixels above a small population threshold. Where both are sparse, footprint = buffer around the settlement node, flagged `footprint_approx` |
| Hex→village link | Each village stores its intersecting hexes and catchments with area and population weights |
| Straddling | A village crossing hexes with different tiers reports both, with the footprint share in each |

`boundary_quality` and `footprint_approx` are shown beside every village alert and added to the confidence reasons. They do not enter the four-factor formula (Section 9.2) until validation shows they change accuracy.

#### 5.3.2 Landslide village value: footprint plus upslope source reach

A failure above a village is a threat even if the source hex lies outside the footprint, so footprint-only scoring is not enough.

1. **Footprint value.** `LS_foot` = 90th percentile of landslide-head risk across footprint hexes. A percentile is used instead of the maximum because taking the max over several noisy hexes biases risk upward, and more so for large villages. Where the footprint has 3 or fewer hexes, the max is used.
2. **Source-reach value.** A hex is a *candidate source* if slope ≥ 15° (provisional) and its landslide risk ≥ Yellow. Its runout is approximated with a **reach-angle rule**: trace downslope along the flow-direction grid, stopping where the angle from the source to the current point falls below `α` (initial `α = 15°`, provisional, fitted from the inventory where runout distances exist). If the traced path enters the footprint, the source counts as **reaching** the village.
3. **Village landslide value.**

```text
LS_village = max( LS_foot ,  max over reaching sources of risk_source )
alert_driver = "footprint" | "upslope_source"   (whichever set the maximum)
```

The reach rule is a screening approximation, not a runout model, and is labeled as such wherever shown.

#### 5.3.3 Flood village value: catchment-anchored

Flash floods reach a village along the channel, not by hex adjacency.

- The village takes the flood tier of the micro-catchment whose stream reach passes through or upstream of the footprint (outlet pour points from Section 5.2, step 4).
- If the footprint intersects the screening inundation extent or the low-HAND stream buffer, the tier is kept. Otherwise it is reduced by one tier, consistent with Section 8.2.
- `alert_driver = "catchment"`.

The HAND extent is only a coarse screen. Its vertical resolution is comparable to the DEM's own vertical error in steep terrain. Wherever it is displayed at village level it is captioned "coarse screening extent, not a per-building flood zone", and no per-house in/out statement is made.

#### 5.3.4 Persistence, with exceptions

To keep single-cycle noise from triggering village alerts:

- A village tier of **Orange or Red** requires the value to meet that tier in **2 consecutive cycles** before a draft is created.
- **Bypass (immediate draft):** `CLOUDBURST_FLASH`, any sensor-confirmed trigger (rain, tilt, stage) or an edge-node alarm. Little lead time is available in these cases, so waiting a cycle is not acceptable.
- Once a draft exists, escalation and de-escalation follow Section 9.6 unchanged.

#### 5.3.5 Village record

| Field | Meaning |
|---|---|
| `exposure_weighted_mean` | Population-weighted mean of intersecting hex risks (context only, never used for alerting) |
| `footprint_p90` | `LS_foot` |
| `source_reach_max` | Highest-risk reaching source, or null |
| `alert_value`, `alert_driver` | Value used for the tier and what produced it |
| `footprint_hex_count` | Sample size behind the percentile |
| `boundary_quality`, `footprint_approx` | Section 5.3.1 flags |

### 5.4 What the pipeline does not do

It cannot conjure sensors, event history, or surveyed channel geometry for a new place. Where these are missing it says so (Section 9.2) instead of substituting a default silently.

---

## 6. Data layer

### 6.1 Sourcing principles

- Authoritative Indian sources (IMD, GSI, CWC, ISRO/NRSC) are the production intent; globally scriptable sources are what the working build queries.
- Multi-resolution fusion, stated honestly: terrain ~30 m, land cover 10 m, soil 250 m, regional rainfall/soil-moisture 9–11 km before downscaling.
- Raw observations are kept separate from derived features; derived layers are never presented as independent datasets.
- Every prediction carries per-layer source/quality metadata.
- Leakage rule: `feature_timestamp <= prediction_timestamp`, always.

### 6.2 Availability matrix

| Layer | Source | Access | Resolution | Live? | Role |
|---|---|---|---|---|---|
| DEM | Copernicus GLO-30 / SRTM | OpenTopography | ~30 m | Yes | Terrain, catchments |
| Land cover | ESA WorldCover | Direct fetch | 10 m | Yes | CN, roots |
| Geotechnical | SoilGrids | WCS / GEE **bulk** (REST point API paused) | 250 m | Bulk pre-fetch only | FS inputs |
| Live rainfall state | IMD AWS/ARG if accessible; IMERG Early; Open-Meteo recent-hours | APIs (Earthdata login for IMERG) | gauges / 0.1° / ~10 km | Yes | Dynamic input |
| Forecast rainfall | Open-Meteo / NWP | REST | ~10 km | Yes | Lead-time projection only |
| Live soil moisture | In-situ nodes; Open-Meteo soil moisture; SMAP where fresh enough | MQTT / API | point / ~10 km | Yes | Saturation term |
| Reanalysis | ERA5-Land | Copernicus CDS | ~9–11 km | **No** (days of latency) | Training, back-tests, climatology |
| Inventory | GSI/Bhukosh; public event records | Portal / manual | Points/polygons | Coverage-limited | Labels, thresholds |
| Exposure | WorldPop, OSM buildings/roads/POIs | Downloads / Overpass | 100 m / vector | Static | Priority, shelters |
| Hydro (optional) | CWC gauges; node stage sensors | API / MQTT | Point | Where available | Blockage check |

### 6.3 Rainfall downscaling method (the "hyper-local" claim)

One 10 km rainfall value cannot be honestly called village-level. v2 downscales in three steps and carries the uncertainty forward:

1. **Gauge-anchored merge.** Coarse satellite/NWP rainfall is merged with gauge observations by conditional merging (kriging with external drift on gauge-minus-satellite residuals).
2. **Orographic adjustment.** A terrain factor (elevation, aspect relative to wind, distance to ridge) is fitted to gauge-to-satellite ratios where gauges exist, and applied on the ~1 km grid.
3. **Uncertainty.** Kriging variance (or ensemble spread when no gauges) becomes a per-hex rainfall-uncertainty term. Where the nearest gauge exceeds a set distance, the hex is tagged `rain_coverage: satellite_only` and the input-coverage factor of confidence drops (Section 9.2).

The document does not claim sub-kilometre rainfall skill; it claims a terrain-informed ~1 km field with an explicit uncertainty layer.

### 6.4 One fallback chain

Earlier drafts had two inconsistent chains. v2 uses one, applied per layer:

```text
Tier 0  Healthy local sensor within influence radius (Section 12.2)
   ↓ unavailable / QC-failed
Tier 1  Live regional observation or analysis
        (gauges, IMERG Early, Open-Meteo recent-hours state)
   ↓ unavailable
Tier 2  Last-known-good cached state (age shown), forecast used ONLY
        for projection and never labeled as an observation
   ↓ unavailable
Tier 3  Terrain/physics-only static estimate, confidence flagged down
```

ERA5-Land is never a live tier. It supplies training features, back-test replays and antecedent climatology.

### 6.5 Terms-of-use and licensing checks (before any deployment beyond the demo)

| Source | Point to verify |
|---|---|
| Open-Meteo | Free API is for non-commercial use; production needs a paid plan or self-hosting |
| Google Earth Engine | Free for research/noncommercial; commercial use is licensed |
| IMD / GSI data | Redistribution and real-time use terms; institutional agreement for feeds |
| SoilGrids, WorldCover, WorldPop | Open licences with attribution; confirm current terms |
| OSM | ODbL attribution and share-alike |
| SACHET | Publishing restricted to recognized agencies; sponsorship required |

### 6.6 Data risks

| Risk | Mitigation |
|---|---|
| SoilGrids REST paused | Bulk WCS/GEE pre-fetch; novel location without pre-fetch runs terrain-only, confidence reduced |
| Event-level completeness (date, time, coordinates) | Use every usable event; report per-region counts; LORO gated by minimum-data rule (Section 15.3). Bhukosh is largely locations without event time, so supplement it with SDMA records and public catalogs (for example NASA's Global Landslide Catalog), each event stored with its source |
| Unrecorded events treated as negatives | Negative-sampling rules in Section 8.4 |
| Resolution mismatch | Fused, labeled, never hidden |
| Gauge sparsity | Uncertainty layer plus input-coverage factor |

---

## 7. Hazard engines

MVP engines are **E1–E4 plus the classifier**. GLOF and seismic debris-flow sensing are future scope (Section 19).

### 7.1 E1 — Static susceptibility features

Slope, aspect, TWI, TRI, HAND, flow accumulation, drainage density, distance to stream, elevation, land use, NDVI, curve number, plus `gsi_susceptibility_class` and `historical_event_count_500m` as **explicit-null** features where no inventory exists (never encoded as low or zero).

### 7.2 E2 — Slope stability (landslide engine)

**Governing equation (infinite slope):**

$$FS = \frac{c' + c_s(m) + (\gamma z\cos^2\beta-u)\tan\phi'}{\gamma z\sin\beta\cos\beta}, \qquad u = m\,\gamma_w\,z\,\cos^2\beta$$

Both terms share the same `cos²β` exponent (a previous inconsistency, corrected).

**7.2.1 Saturation term `m` — where sensors enter.** `m` is the saturation fraction of the soil column.

| Situation | Source of `m` |
|---|---|
| Healthy sensor within influence radius | `m = clip((θ − θ_r) / (θ_sat − θ_r), 0, 1)` from measured volumetric water content, with distance/terrain-class decay outside the node's own hex |
| No sensor | Gridded soil moisture (Open-Meteo/SMAP) mapped through the same relation, plus antecedent-rain index |

Equating degree of saturation with water-table fraction is a simplification; it is stated in the limitations and is why FS remains an index. A hex whose FS used sensor data is tagged `sensor_adjusted` on the map.

**Matric-suction cohesion `c_s(m)`.** In unsaturated lateritic and residual soils, matric suction acts as apparent cohesion and is lost as infiltration raises saturation. v2 models it as `c_s(m) = c_s0 · (1 − m)`, so it vanishes as `m → 1`. `c_s0` is zero by default and non-zero only where onboarding flags a laterite/residual class (Section 5.2, step 6); its bounds are literature-derived, recorded with citations in the data dictionary, and provisional until checked against local laboratory data. The linear decay is a screening simplification of the soil-water characteristic curve and is stated in the limitations. It is what makes FS fall sharply near saturation in laterite classes.

**7.2.2 Uncertainty: soil parameters and depth.** `FS_p05 / FS_p50 / FS_p95` come from Monte-Carlo draws (order of hundreds to a thousand):

- `c'`, `φ'`, `γ` sampled within SoilGrids' published 5th–95th percentile bounds, propagated through the pedotransfer relation.
- **Soil depth `z` sampled over a plausible range** (default depth ± a slope-dependent spread; wider where the depth is a flagged default rather than a product value). Depth is the most sensitive infinite-slope input, so it is not left as a point value.
- Root cohesion added from land-cover class as a bounded, uncertain term.
- `c_s0` (suction cohesion) sampled within its literature-derived bounds wherever a laterite/residual class is flagged.
- Where `has_local_calibration = false`, the band is widened by a factor `w` (initial value 1.5, tuned in validation) to reflect applying temperate-soil pedotransfer to unstudied terrain.

Derived quantities: `P(FS<1)` from the draws, and

`FS_band_penalty = min(0.6, (FS_p95 − FS_p05) / (2·FS_p50))`, multiplied by `w` when uncalibrated (capped).

**7.2.3 Rainfall intensity–duration threshold (fitted, not guessed).**

- Fit `I = α · D^(−β)` as a lower-envelope (e.g., 5th-percentile quantile regression) over triggering-rainfall events in the pooled inventory, per physiographic class where enough events exist.
- Where a class lacks events, fall back to a published global/regional threshold (for example the Caine 1980 relation) and flag it as a fallback; such thresholds are known to transfer imperfectly.
- Output `R_int = I_obs / I_threshold(D)` per hex, used by the classifier and as an ML feature.
- The same fitted thresholds seed the edge-node rules (Section 12.2), so edge thresholds are calibrated rather than arbitrary.

FS is one input to the landslide head; it is never presented as a standalone prediction or a substitute for a site survey.

### 7.3 E3 — Micro-catchment runoff and flood engine

Flash floods are catchment processes; a hex grid alone ignores upstream contribution. E3 runs per micro-catchment, then maps results back to hexes and villages.

| Step | Method |
|---|---|
| Effective rainfall | Catchment-mean downscaled rainfall over the concentration window |
| Runoff depth | SCS curve number: `Q = (P − Ia)² / (P − Ia + S)`, `S = 25400/CN − 254` (mm), `Ia = 0.2·S` (sensitivity-tested); CN adjusted for antecedent moisture from soil moisture / antecedent rain |
| Time of concentration | Kirpich: `Tc = 0.0195 · L^0.77 · S^(−0.385)` (minutes; `L` in m, `S` in m/m) |
| Peak discharge | SCS triangular hydrograph: `Tp = D/2 + 0.6·Tc`, `qp = 0.208·A·Q / Tp` (m³/s, A in km², Q in mm, Tp in h) |
| Catchment-level flood indicator | `qp` relative to a catchment-class reference (from the inventory where flood events exist, otherwise a percentile of simulated peaks) |
| Inundation (screening) | HAND-based extent: cells with `HAND ≤ h(qp)`, with stage `h` from a Manning-type rating on a DEM-estimated cross-section. Computed only for Orange/Red |

This is deliberately a conceptual, zero-survey model. It cannot replace the 2-D hydrodynamic models that need surveyed channel geometry, and the inundation layer is labeled "screening-grade estimate" wherever shown. ML residual correction (LSTM/GNN) is a later upgrade once event data justifies it.

### 7.4 E4 — Stream-blockage / dam-formation check (sensor-dependent)

Runs only where a paired upstream/downstream stage sensor exists or a CWC gauge sits on the reach; otherwise it is **off and labeled off**, never guessed.

```text
blockage_suspect =
    landslide head ≥ Orange in upstream catchment  (or node tilt alarm)
    AND downstream stage falling ≥ ΔH_down over Δt
    AND upstream stage rising ≥ ΔH_up over Δt
```

Thresholds are initial values tuned in back-tests. Output: a flag that raises the flood-head input and sets `trigger_type = LANDSLIDE_DAM`. It also flags road segments that intersect the blocked reach for the evacuation module (Section 11).

### 7.5 TC — Trigger-type classifier (rule-based)

No ML is claimed. The classifier reads engine outputs and labels the dominant mechanism so alert text and lead-time expectations match the hazard.

| Trigger type | Rule (initial thresholds, tuned in back-test) | Alert action emphasis |
|---|---|---|
| `CLOUDBURST_FLASH` | `R_int ≥ 1` on a short window **and** soil not yet saturated (`m < 0.7`) **and** flood indicator high | Leave stream banks/low ground now |
| `SATURATION_FLOOD` | `R_acc ≥ 1` (antecedent accumulation) **and** `m ≥ 0.7` **and** flood head ≥ Orange | Move from riverbank/low ground before peak |
| `SATURATION_LANDSLIDE` | `m ≥ 0.7` **and** (`P(FS<1)` high or landslide head ≥ Orange) **and** rain persisting | Move away from steep slopes and below cuts |
| `LANDSLIDE_DAM` | E4 flag | Evacuate downstream of the blocked reach; expect delayed surge |
| `COMPOUND_CASCADE` | `SATURATION_LANDSLIDE` **and** flood head ≥ Orange in the same or downstream catchment | Combined advice, highest priority |

Where rules disagree or inputs are missing, `trigger_type = UNSPECIFIED` and the alert uses generic wording. The rule outputs are also logged as validation features. The saturation boundary (`m = 0.7`) is shared by the cloudburst and saturation-flood rules so no range of `m` falls through to `UNSPECIFIED` by construction; the value is tuned in back-test.

---

## 8. ML fusion layer

### 8.1 Role

The ML layer is a learned fusion over already physically meaningful engine outputs (FS distribution, threshold exceedance, catchment runoff) plus terrain and dynamic state. It does not learn slope stability or hydrology from scratch, and its skill is bounded by the engines' limits and by training-data asymmetry across regions.

### 8.2 Two hazard heads, one shared feature table

Earlier drafts produced a single risk score while the dashboard and validation needed flood and landslide separately. v2 defines two heads:

| Head | Unit of prediction | Label | Output |
|---|---|---|---|
| Landslide head | hex × time | Documented landslide within the hex/time window | `risk_ls`, `P_class_ls` |
| Flood head | micro-catchment × time | Documented flash flood in the catchment/time window | `risk_ff`, `P_class_ff` |

Each is an XGBoost classifier trained separately on the shared features (XGBoost is chosen for small, imbalanced, heterogeneous tabular data and native missing-value handling). Hex-level flood tier = the catchment flood tier if the hex lies within the screening inundation footprint or a low-HAND stream buffer (initial 5 m), otherwise reduced by one tier. **Compound** view = the higher of the two tiers per hex, never an average, with a dual-tier indicator when they differ.

Because the heads learn the fusion, there are no hand-set engine weights. The trigger classifier (Section 7.5) is separate and only names the mechanism.

### 8.3 Feature table (32 features)

Carried from HydraSense (Final) with these changes:

| Change | Reason |
|---|---|
| `has_local_calibration` **removed from model features** | Training regions with events are calibrated by definition, so the flag is near-constant in training and out-of-distribution in leave-one-region-out. It is used only in the confidence layer |
| `simulated_ffgs_signal`, `simulated_gsi_signal` **removed from model features** | Simulated inputs have no historical counterpart; keeping them would contaminate validation. They appear in the demo UI only, labeled simulated |
| FS band features renamed `fs_p05`, `fs_p50`, `fs_p95` | Now produced by Monte-Carlo over soil parameters and depth |
| 6 new features | `r_int` (I–D exceedance ratio), `p_fs_lt1`, `scs_runoff_mm`, `tc_min`, `catchment_area_km2`, `iot_soil_moisture` (nullable) |

Arithmetic: 29 inherited − 1 (`has_local_calibration`) − 2 (simulated signals) + 6 new = **32**.

`gsi_susceptibility_class` and `historical_event_count_500m` stay as explicit-null features. Performance is always reported with and without `gsi_susceptibility_class` because it is partly derived from the same inventory used for labels.

### 8.4 Training data and negative sampling (specified)

Positives come from the pooled multi-region inventory with event-level completeness (date, time, coordinates). Regions are not balanced artificially; per-region counts are reported.

Negative sampling rules (initial settings, with sensitivity checks):

| Rule | Setting |
|---|---|
| Ratio | 5 negatives per positive initially; sensitivity at 2:1 and 10:1 |
| Spatial exclusion | Negatives at least 3 hex rings from any recorded event of the same hazard |
| Temporal matching | Negatives drawn from the same season and comparable rainfall-day distribution as positives, so the model learns hazard signal, not seasonality |
| Unmapped areas | Negatives in areas with incomplete inventories are down-weighted (initial 0.5) because some may be unrecorded events |
| Leakage | All rows of an event (every offset) stay in one fold |

### 8.5 Event-centered temporal sampling

Each event contributes samples at offsets **T−72, −48, −24, −12, −6, −3, −1 h**. The added −3 and −1 h offsets are the reason the system can support sub-6-hour claims at all; without them the training never sees the final hours. These are additional samples of one event, not independent events, and never split across folds. Sub-hour claims are supported only by sensors/nowcast and the edge tier, not by the fused hourly model.

### 8.6 Explainability

Global `feature_importances_` for model review. **SHAP (`TreeExplainer`) is a must-build**, because the console's per-village explanation panel (Section 13.3) needs per-prediction contributions, not global ranks. Collinear groups (rainfall windows, terrain wetness indices) are labeled at group level so no single correlated feature appears to carry the weight.

### 8.7 Alternatives kept

Random Forest as a sanity baseline; PSO-BP only if an implementation already exists and only compared where datasets match; LSTM/GRU after the pooled event count justifies it.

---

## 9. Decision engine

### 9.1 Risk score and tiers

Each head's probability is scaled to `risk 0–100`. Default cut points, **pending calibration**:

```text
Green 0–29 | Yellow 30–54 | Orange 55–74 | Red 75–100
```

These are project thresholds, not official warning levels. After leave-one-region-out runs, cut points are reset from the reliability diagram (where predicted probability separates true from false alarms), **separately for calibrated and uncalibrated regions**, and the fitted values replace the defaults in the frozen validation package (Section 15.9).

### 9.2 Confidence: four computed factors

```text
Confidence = 100 × P_class × (1 − Eng_penalty) × C_cal × C_in
```

`Eng_penalty` is the engine-uncertainty term of the hazard being scored. For the **landslide head** it is `FS_penalty` (Section 7.2.2). For the **flood head** it is built from rainfall-merge variance and curve-number / time-of-concentration sensitivity (spread of `qp` under plausible CN and Tc ranges, scaled to 0–0.6 the same way).

| Term | Meaning | Source |
|---|---|---|
| `P_class` | The head's own class probability (statistical) | Section 8 |
| `1 − Eng_penalty` | Engine-side uncertainty: geotechnical/depth for landslide, rainfall/CN/Tc for flood | Sections 7.2.2, 7.3; landslide band already widened when uncalibrated |
| `C_cal` | Has the pooled model any local event experience for a region like this | 1.0 if GSI-mapped or usable local inventory; otherwise `k < 1` |
| `C_in` | **Input coverage**: how much of the live state is local observation vs. satellite/forecast vs. cached | 1.0 with a healthy local sensor and gauge coverage; lower for satellite-only, cached or fallback tiers |

`C_cal` and `C_in` are separate on purpose. A region can have plenty of inventory yet no live sensors, or the reverse, and the two gaps mean different things to a duty officer. `k` and the `C_in` levels are **fitted, not fixed by inspection**: after leave-one-region-out runs, bin raw confidence and compare with observed hit rate per data-availability tier, then set the constants (or replace the product with an isotonic mapping) so the displayed number tracks accuracy. Until then the constants are labeled provisional.

**Worked example (arithmetic checks):**

```text
Uncalibrated, satellite-live inputs, same head probability:
  Risk 82, P_class 0.91, Eng_penalty 0.23 (widened), C_cal 0.75, C_in 1.00
  Confidence = 100 × 0.91 × 0.77 × 0.75 × 1.00 = 52.6 → 53

Calibrated, healthy local sensor:
  Risk 82, P_class 0.91, Eng_penalty 0.15, C_cal 1.0, C_in 1.00
  Confidence = 100 × 0.91 × 0.85 × 1.0 × 1.00 = 77.4 → 77
```

Same risk, same model confidence, visibly different displayed confidence, for stated reasons. This is an **engineered index**, not a calibrated probability of correctness; wherever shown, it is described as "a combined uncertainty and data-coverage indicator". The four factors always travel with it (dashboard, API, CAP parameters).

### 9.3 Village roll-up

Per village and per hazard: `alert_value` and `alert_driver` (Section 5.3), the exposure-weighted mean for context only, the dominant `trigger_type`, confidence with reasons, and the lead-time range below.

### 9.4 Lead time — per mechanism, hour-resolution

**Method.** Forecast rainfall is projected forward; dynamic features (rainfall windows, antecedent index, saturation, FS distribution, runoff) are recomputed at hourly horizons; the trained heads are re-run; the earliest projected Red crossing sets the lead time. Reported as a **range bucket**, never as minutes:

`<1 h (detection only) · 1–3 h · 3–6 h · 6–12 h · 12–24 h · no Red crossing in forecast window`

Interpolation between hourly points is labeled as interpolation. Lead time inherits forecast uncertainty (which grows with horizon and is worst for convective rainfall) and FS uncertainty, and is displayed with the same confidence as the risk it belongs to.

**Design expectations by mechanism (to be verified in back-tests, not promised):**

| Trigger type | Realistic lead time | Basis |
|---|---|---|
| `CLOUDBURST_FLASH` | Minutes to ~2 h, and only with nowcast rainfall, upstream stage rise or a local sensor; otherwise "detect and alert, little or no lead time" | Convective rain is hard for ~10 km models; edge tier matters most here |
| `SATURATION_FLOOD` | Several hours, forecast-limited | Antecedent wetness plus forecast |
| `SATURATION_LANDSLIDE` | Hours to a day or more, forecast-limited | Slow soil wetting, threshold exceedance ahead of failure |
| `LANDSLIDE_DAM` | Hours after detection, sensor-dependent | Blockage precedes outburst; disabled without stage sensors |

### 9.5 Threat products

Aligned with the vocabulary of the national system: **Risk** (present-moment tier), **Imminent Threat** (first projected Red crossing, bucketed), **Persistent Threat** (tier Orange/Red across the last N cycles with rising saturation). All three are repackagings of the same model output at different time slices and are described that way if asked.

### 9.6 Anti-flapping (hysteresis)

Escalation is immediate; de-escalation requires N consecutive lower cycles (initial N = 2). Adjacent hexes/villages triggering together merge into one alert polygon. Creating the first village-level draft additionally follows the two-cycle persistence rule and its bypasses (Section 5.3.4).

---

## 10. Alerting and governance

### 10.1 Baseline pipeline

```text
Village/hex reaches Orange/Red (or projected Red within window)
   → alert service builds CAP 1.2 object
   → held in PENDING for two-person authorization
   → on authorization: SACHET-compatible webhook / Cell Broadcast-ready output
   → dashboard feed + field-team task list
```

### 10.2 CAP payload

Standard fields (`identifier`, `status`, `msgType`, `event`, `urgency`, `severity`, `certainty`, `headline`, `description`, `area`) populated from the triggering product, plus CAP `<parameter>` extensions so the honesty signal survives outside the dashboard:

`confidence_score`, `confidence_factors` (model / FS / calibration / input coverage), `has_local_calibration`, `trigger_type`, `lead_time_bucket`, `data_source_quality`, `village_names`, `sensor_adjusted`, `alert_driver`, `boundary_quality`.

The plain-language description states calibration status and lead-time caveats in words, in the official regional language resolved from the admin hierarchy. The payload follows CAP 1.2 (OASIS; ITU-T X.1303). A sample is in Appendix B.

### 10.3 Lifecycle and safeguards

| Event | Behavior |
|---|---|
| New Orange/Red | `msgType=Alert`, new identifier |
| Same tier next cycle | Suppressed (cooldown); dashboard updates silently |
| Tier change | `msgType=Update`, same identifier |
| Drops to Green/Yellow for N cycles | `msgType=Cancel` |
| First cycle after onboarding | **Cold-start guard**: no alert can fire until one full cycle completes |
| Any Orange/Red draft | **Two-person authorization** (duty officer + district authority or delegate) before dispatch |

Imminent Threat produces an `urgency=Expected` alert with the projected bucket; Persistent Threat is appended as an update parameter to the open Risk alert, never a third independent alert.

**Alert-burden metric.** Alarms per village per season, false-alarm ratio and consecutive-alarm count are tracked (Section 15) because false-alarm fatigue is the main threat to evacuation compliance.

### 10.4 Action text by trigger type

Templates draw from Section 7.5 (e.g., "Move away from stream banks now" versus "Move away from steep slopes and areas below road cuts"), always naming villages, the nearest shelter (Section 11), and the confidence caveat when confidence is low or uncalibrated.

### 10.5 Dissemination reality

SACHET accepts feeds only from recognized government agencies, so HydraSense output is a **technical-readiness demonstration** until a State SDMA, GSI, CWC or NDMA sponsors integration. Cell Broadcast is a better fit than SMS for short-fuse alerts and CAP is channel-agnostic, so nothing needs redesign when sponsorship exists (re-verify current channel status before citing).

**Cell Broadcast text.** Full CAP descriptions will not fit a broadcast page, so each alert also carries a short broadcast template, built from the same fields:

```text
{TIER} {hazard} risk: {village}. {first action}. Confidence: {low|medium|high}. Ref {id}
```

Broadcast pages are short (roughly 90 characters per page in GSM 7-bit, multi-page concatenation possible), so the exact limit and the language and encoding rules must be checked against the current specification before the template is frozen. The confidence word maps from the fitted confidence bands (Section 9.2), not from the raw index.

| Property | Traditional SMS | Cell Broadcast |
|---|---|---|
| Transmission | Point-to-point, queued | One-to-many, simultaneous within a geofence |
| Latency in mass emergencies | Can be minutes or worse when congested | Seconds (dedicated signaling channel) |
| Congestion exposure | High | Low |
| Recipient numbers needed | Yes | No |

*The comparison comes from the evaluation report and needs verification against C-DoT/NDMA documentation before it is cited.*

### 10.6 Offline-first tier (standard, not optional)

| Layer | Function | Depends on |
|---|---|---|
| L0 Edge | On-device rule → siren/blinker; solar + battery | Nothing above it |
| L1 Local relay | Node → LoRa → gateway → SMS to registered caretaker | GSM voice/SMS, which typically outlasts data |
| L2 Cloud fusion | Sections 5–9 | Internet |
| L3 Digital dissemination | CAP / SACHET / Cell Broadcast | Internet + sponsorship |
| L4 Human relay | Per-village nodal contact receives whichever layer is reachable and performs the physical notification | People |

| Connectivity state | Still works | Lost |
|---|---|---|
| Full | Everything | Nothing |
| Internet down, GSM up | L0, L1, L4 | Regional risk, confidence, lead time, dashboard |
| Total blackout | L0 | Everything but the local alarm |
| Cloud outage | L0, L1, L4 | Fusion outputs |

The edge rule is simpler and less accurate than the fusion model; it trades accuracy for guaranteed availability, and that trade-off is stated wherever it is described. Mesh routing is out of scope. Villages without an edge node are marked `L3-only` on the map.

---

## 11. Exposure, priority and evacuation

### 11.1 Exposure and vulnerability (MVP indices)

| Component | Source |
|---|---|
| Population per village/hex | WorldPop |
| Buildings, density | OSM buildings |
| Critical facilities (schools, health, shelters) | OSM POIs, SDMA lists where available |
| Roads and access | OSM road network |
| Vulnerability index | Simple composite (built-up density, road access, age-sex shares if available) |

`Priority = (risk/100) × Exposure × Vulnerability`, normalized within the region. This is a **ranking index for allocating attention**, not a calibrated loss estimate. Full impact modelling is roadmap.

### 11.2 Evacuation advisory (MVP)

1. **Village→shelter mapping.** Nearest candidate shelters from OSM/SDMA lists by road-network distance, with capacity when known.
2. **Blockage-aware.** Road segments intersecting Orange/Red hexes, the screening inundation footprint, or a blocked reach (E4) are excluded before choosing a route.
3. **Output.** Recommended shelter and route as an advisory polyline plus text; village priority table for the duty officer.

This is an advisory, not a certified evacuation plan. Dynamic multi-vehicle routing, shelter capacity balancing and traffic are future scope.

---

## 12. IoT and edge layer

### 12.1 Node specification

| Sensor | Purpose |
|---|---|
| Tipping-bucket rain gauge | Intensity, accumulation, gauge anchor for downscaling |
| Capacitive soil moisture (two depths) | Saturation `m` for FS |
| Soil temperature probe | Temperature compensation of the capacitive readings |
| Tilt / extensometer | Slope movement precursor |
| Stream level (ultrasonic/radar) | Flood stage and blockage check |
| Siren/blinker, solar + battery, LoRa + GSM | Edge alert and uplink |

Optional: piezometer for pore pressure where the site justifies it.

### 12.2 Ingestion, QC, sensor-snapping and edge rules

```text
MQTT topic:  hs/{region}/{node}/{metric}      payload: value, unit, ts, battery, qc
QC:          range check, spike/stuck detection, rate-of-change, battery/comm health,
             temperature compensation (soil-temperature probe),
             salinity/over-read flag (persistently high θ with no rain response),
             air-gap flag (sudden step-drop or two-depth disagreement),
             cross-check against nearby gauge rainfall and satellite soil moisture
Health:      node marked healthy / degraded / offline; feeds C_in and the fallback chain
Snapping:    healthy node overrides gridded input inside its own hex, with
             distance- and terrain-class decay inside the same micro-catchment
             (initial radius ~1.5 km, tuned); overridden hexes tagged sensor_adjusted
Rainfall:    gauge readings anchor the downscaling residuals (Section 6.3)
```

**Capacitive-sensor error handling.** Capacitive probes drift with soil temperature, over-read in saline soil, and read air where soil contact is lost. Each node therefore gets a per-node gravimetric calibration before deployment (fitted `θ_r` and `θ_sat` stored per node and used in Section 7.2.1), drift is logged, and persistent disagreement with the independent references above marks the node `degraded`, so it falls to Tier 1 in the fallback chain (Section 6.4). A reading that fails QC is never used as ground truth.

**Edge rule (per node):**

```text
if rain_1h ≥ τ_int(site)
   or (rain_24h ≥ τ_acc(site) and θ ≥ θ_crit(site))
   or tilt_rate ≥ τ_tilt:
       siren + SMS to caretaker
```

`τ_int` and `τ_acc` come from the fitted I–D threshold for the site's class plus a safety margin (Section 7.2.3); `θ_crit` from soil parameters; all editable by the SDMA. This is what makes the edge tier calibrated rather than arbitrary.

### 12.3 Sensor-siting ranking

Where should the next sensors go? Onboarding produces a ranked list, not a uniform grid.

```text
candidate sites:  hexes with slope/accessibility constraints and a gateway viewshed
site score s_i =  Σ over uncovered villages v within radius R:
                  susceptibility_v × exposure_v × connectivity_i × accessibility_i
selection:        greedy — pick the highest marginal gain, mark villages covered, repeat
                  until budget N is spent
```

Connectivity uses a DEM viewshed to candidate gateways. The output shows the selected sites, villages newly covered, and remaining uncovered high-priority villages, which is also the honest answer to "how many sensors does a district need".

### 12.4 Economics, ownership and upkeep

| Item | Figure / approach |
|---|---|
| Prototype node (ESP32 + basic sensors + hooter + solar) | Roughly ₹1,500–2,500 per the earlier estimate; prototype-grade only |
| Field-grade nodes (IP-rated enclosure, better sensors, larger solar/battery), gateway, tower/mount | **[to be quoted]** |
| Connectivity | SMS/GSM per tariff **[to be quoted]** |
| Calibration | Per-node gravimetric calibration before deployment; re-check before monsoon and mid-season; drift logged per node |
| Spares and theft/damage | Low-value components, tamper flag, community custodian per node |
| Owner and O&M | State SDMA / district authority as owner; panchayat/community custodian as first-line maintainer |
| District cost | `N_nodes × (amortized hardware + annual O&M) + gateways + comms`, computed from quoted values |

### 12.5 Simulation policy

One or two physical nodes if the team has the skills; otherwise a labeled replay stream. Remaining nodes are simulated MQTT publishers, always displayed as `simulated`. A deliberate mid-demo sensor failure shows fallback to the next tier (Section 16). Nothing simulated is ever presented as measured.

---

## 13. Dashboard and user experience

### 13.1 Questions the console must answer at a glance

Where is the risk? How severe, and which hazard? Why (which mechanism)? How confident, and why? How much lead time? Which villages first? Where do people go?

### 13.2 Roles

| Role | Job |
|---|---|
| Decision Authority (district/state duty officers) | See the full picture, authorize dispatch, own the action plan |
| Response Unit (field teams) | Receive assigned villages/routes, report status; sees no explainability stack |

No standalone citizen app; citizen delivery goes through SACHET/Cell Broadcast. A small captioned citizen-preview panel inside the console shows how a payload would render. The chain-of-command breadcrumb and local-script font are resolved from the admin-hierarchy lookup, never hardcoded.

### 13.3 Decision Authority console (three fixed zones)

| Zone | Content |
|---|---|
| Header | Resolved chain of command, clock, situation pill, two-person **[AUTH]** state (mirrors the backend gate), role switcher, legend, a greyed "National view — future" tab |
| Left | Append-only event log, alert activation record, audit-hash strip, silent refreshes with a single pulse for genuine new alerts |
| Center | Literal H3 hexagon map with **Compound / Flood / Landslide** toggle (Compound = higher tier, dual-tier edge marker when they differ); micro-catchment outlines; village polygons with tier chips; time scrubber (−72 h to forecast window); sensor layer (real / simulated / suggested sites) |
| Right | Explainability: rainfall/soil sparkline, FS shown as `p05–p50–p95` bracket with a "widened, no local calibration" tag, catchment runoff indicator, feature-contribution bars (group-labeled), trigger-type badge, editable action plan |
| Bottom strip | Validation and data-health panel (frozen LOEO/LORO figures, dated; per-layer live/cached/fallback list) |
| Footer | Agency/source connection dots, quiet when healthy |

**Village table** (sortable by priority): village, worst tier, hazard, trigger type, lead-time bucket, confidence with reason, nearest shelter, edge-node status (`L3-only` if none).

**Confidence traces to a reason.** Hover on a desaturated hex or village shows the dominant reduced factor in one line ("no local historical calibration", "widened geotechnical uncertainty", "satellite-only rainfall", "cached soil layer"). A separate hollow/filled corner dot shows alert-resilience (edge tier present or not), kept distinct from prediction confidence.

**Degraded mode.** If a layer drops down the fallback chain, a banner names the layer and age, panel borders turn caution-yellow with a "cached · Xm ago" tag, and the output continues with lower confidence rather than failing.

**Style rules.** Near-black surfaces; saturated color only for the four tiers, always with a word label; checked in a color-blindness simulator; IBM Plex Mono for numbers, Plex Sans for text; motion only in response to an action or a real state change; print/briefing export.

### 13.4 Response Unit view

Own position in the breadcrumb, read-only authorization, assigned villages/routes/ETAs, larger touch targets, last-received plan and map persisted offline on the device.

### 13.5 Usability test protocol (to be run; results go in Appendix E)

| Item | Plan |
|---|---|
| Participants | 3–5 people unfamiliar with the system (students plus, if reachable, a district disaster-management staffer) |
| Tasks | (1) Find the highest-priority village. (2) State its hazard, lead-time range and confidence. (3) Explain why confidence is lower than another village's. (4) Review and authorize or reject a drafted alert |
| Measures | Task completion time, errors, comprehension answer for task 3, System Usability Scale (SUS) |
| Rule | Timing claims are made only from this test, never asserted in advance |

---

## 14. Backend, API and stack

### 14.1 Architecture

```text
React (deck.gl H3HexagonLayer + MapLibre GL)
   ↕ REST + WebSocket (snapshot on connect, then deltas)
FastAPI
   ↓
GeoPackage per region (SQLite + spatial index) via GeoPandas
   ↓
Physics / hydrology / ML services (Sections 7–9)
   ↓
Onboarding pipeline (Section 5)  ⇄  Ingestion (rainfall, soil, IoT via MQTT)
   ↓
External APIs and datasets (Section 6)
```

Datastore choice is scale-matched (hundreds to low thousands of hexes per region, single writer); revisit PostgreSQL + PostGIS for continuous multi-region or multi-writer operation.

### 14.2 Core data contract (village level, per hazard)

```json
{
  "village_id": "auto-resolved-id",
  "region_code": "auto-resolved-slug",
  "timestamp": "2026-09-27T14:32:00+05:30",
  "worst_tier": "RED",
  "priority_rank": 1,
  "boundary_quality": "osm",
  "footprint_approx": false,
  "hazards": {
    "landslide": {
      "risk_score": 82, "tier": "RED",
      "confidence_score": 53,
      "confidence_factors": {
        "model_probability": 91, "engine_uncertainty": 77,
        "calibration": 75, "input_coverage": 100
      },
      "factor_of_safety": {"p05": 0.82, "p50": 0.96, "p95": 1.11, "p_fail": 0.58},
      "fs_band_widened_for_no_calibration": true,
      "village_value": {
        "alert_value": 82, "alert_driver": "upslope_source",
        "footprint_p90": 74, "source_reach_max": 82,
        "exposure_weighted_mean": 58, "footprint_hex_count": 6
      }
    },
    "flood": {
      "risk_score": 61, "tier": "ORANGE",
      "confidence_score": 47,
      "confidence_factors": {
        "model_probability": 78, "engine_uncertainty": 80,
        "calibration": 75, "input_coverage": 100
      },
      "catchment_id": "c-0142", "peak_discharge_index": 0.74
    }
  },
  "trigger_type": "SATURATION_LANDSLIDE",
  "lead_time_bucket": "3–6 h",
  "threat_products": {
    "risk": "RED",
    "imminent_threat": "RED in 3–6 h",
    "persistent_threat": "ELEVATED (3/3 windows)"
  },
  "sensor_adjusted": false,
  "instrumented": false,
  "data_source": {"terrain": "live", "soil": "cached", "rainfall": "live", "sensor": "none"},
  "nearest_shelter": {"name": "…", "route_status": "open", "distance_km": 2.4},
  "top_contributing_features": ["rain_6h", "soil_saturation_ratio", "fs_p50", "twi"]
}
```

Arithmetic check for the landslide block: 0.91 × 0.77 × 0.75 × 1.00 = 0.526 → 53. Flood: 0.78 × 0.80 × 0.75 × 1.00 = 0.468 → 47. `engine_uncertainty` is the FS-band term for the landslide head and the rainfall/CN/Tc sensitivity term for the flood head.

### 14.3 Endpoints

```text
POST /region/resolve?query=…                   boundary, catchments, villages
GET  /risk/map?region=…&bbox=…&hazard=…        hex layer
GET  /village/{id}/risk                        contract above
GET  /village/priority?region=…                ranked table
GET  /catchment/{id}/flood                     runoff, Tc, peak index
GET  /risk/{hex_id}/history | /uncertainty
GET  /confidence/{id}/breakdown                four factors with reasons
GET  /sensors/status | /sensors/placement      health; ranked candidate sites
GET  /evacuation/{village_id}                  shelter + route advisory
GET  /validation/loeo | /validation/loro | /validation/backtest | /validation/pilot
POST /alert/trigger | /alert/authorize
GET  /alert/feed
WS   /live/{region}                            snapshot then deltas
```

Inundation is computed only for Orange/Red, enforced in backend code.

### 14.4 Stack

| Layer | Choice |
|---|---|
| Core | Python 3.11+, NumPy, Pandas |
| Geospatial | GeoPandas, Shapely, PyProj, Rasterio (PyPI wheel bundles GDAL), richdem/whitebox/pysheds (terrain, catchments), h3-py v4 |
| Interpolation | SciPy / PyKrige (merging, kriging) |
| Network/routing | OSMnx / NetworkX (shelter routes) |
| ML | scikit-learn, XGBoost, SHAP |
| Backend | FastAPI, APScheduler `AsyncIOScheduler` (`max_instances=1`), WebSocket |
| Datastore | GeoPackage per region |
| IoT | MQTT (Mosquitto), Python client; ESP32 nodes; LoRa |
| Frontend | React, deck.gl `H3HexagonLayer`, MapLibre GL via `react-map-gl/maplibre` (token-free basemap) |
| Deployment | Docker + Docker Compose |

### 14.5 Folder structure (additions marked +)

```text
hydrasense/
├── backend/ (routes, services: orchestrator, tier_state, connection_manager)
├── onboarding/ (boundary, dem, landcover, soil_derivation, h3_grid,
│                + catchments.py, + villages.py, historical_context_check.py)
├── physics/ (infinite_slope.py, uncertainty.py [MC over params + depth])
├── + hydrology/ (scs_cn.py, tc_kirpich.py, peak_discharge.py, inundation_hand.py,
│                 blockage_check.py)
├── + classifier/ (trigger_type.py)
├── ml/ (features.py [32], sampling.py [+negatives], train_landslide.py,
│        train_flood.py, validate_loeo|loro|loco|spatial.py, backtest.py, pilot_run.py, explain.py)
├── ingestion/ (rainfall_merge.py [+downscaling], forecast.py, soil.py, iot.py, fallback.py)
├── + iot/ (node_firmware/, mqtt_ingest.py, qc.py, snapping.py, edge_rules.py)
├── + placement/ (siting_rank.py)
├── + exposure/ (worldpop.py, osm_features.py, vulnerability_index.py, priority.py)
├── + evacuation/ (shelters.py, route_advisory.py)
├── alerts/ (cap.py, authorization.py, sachet.py, templates/ by trigger_type)
├── frontend/ (map, dashboard, alerts, validation, villages)
├── data/ (static, historical/<region>/, shelters, cached_demo/)
└── docs/ (architecture, data_dictionary, validation, limitations)
```

---

## 15. Validation and evidence plan

### 15.1 Principles

Random row or pixel splits inflate results because samples from one event and neighboring hexes are near-identical. v2 layers several holdouts, reports per-hazard and per-region, and freezes results together before any claim is shown.

### 15.2 Splits

| Split | Holds out | Tests |
|---|---|---|
| **LOEO** | All timesteps of one event | Generalization across events in seen regions |
| **LORO** | Every event and timestep of one region; predictions use only what onboarding would compute for a new place | Cross-region transfer: the region-agnostic claim |
| **Leave-one-catchment-out (LOCO)** | All rows of one micro-catchment | Whether flood skill transfers across catchments |
| **Spatial block** | Contiguous hex blocks larger than the terrain autocorrelation range | Whether skill is just terrain memorization |
| **Temporal holdout** | Latest season(s) | Behavior on future monsoons |

### 15.3 Minimum-data rule

LORO is reported as **evidence** only if at least three regions each contribute a stated minimum number of events (initial rule: 15 per hazard). Otherwise it is labeled **illustrative**, with fold counts shown, and the region-agnostic claim is limited to architecture. LORO is reported **per held-out region**, never only pooled, and flood/landslide are always separate.

### 15.4 Metrics

| Family | Metrics |
|---|---|
| Event detection | POD (hit rate), FAR, CSI, missed-event list |
| Discrimination | PR-AUC (ROC-AUC where meaningful), precision, recall, F1 |
| Probability quality | Brier score, reliability diagram, per data-availability tier |
| Warning performance | Lead-time distribution (median, IQR, minimum), timing error, detection-before-onset rate |
| Alert burden | Alarms per village per season, consecutive-alarm count, false-alarm ratio |
| Uncertainty | Coverage of FS `p05–p95` band against outcomes where available |

Accuracy alone is not used (extreme class imbalance).

### 15.5 Baselines and ablations

| Baseline | Purpose |
|---|---|
| Global I–D threshold only (published relation) | Do we beat a simple rule? |
| FS only | Value of ML over physics |
| ML without physics/catchment features | Value of physics |
| SAsiaFFGS-style rainfall guidance (simulated or rain-only) | Value over national guidance, with the simulation stated |

| Ablation | Question |
|---|---|
| Without `gsi_susceptibility_class` | Circularity: how much skill rests on one inventory-derived feature |
| Without IoT features | Value of local sensors |
| Without catchment features (E3) | Value of the flood engine |
| FS band widening on/off | Does widening improve uncertainty coverage |

### 15.6 Validating confidence

The confidence check is not "does held-out confidence come out lower" (that is true by construction when `C_cal < 1`). It is: **does displayed confidence track observed hit rate per data-availability tier?** Bin raw confidence, compare against realized accuracy for calibrated versus uncalibrated regions and sensor versus satellite-only inputs, then fit `k` and the `C_in` levels (or an isotonic mapping) from those curves. Unflattering results are reported.

### 15.7 Negative-sampling sensitivity

Re-run with negative ratios 2:1, 5:1, 10:1 and with unmapped-area negatives excluded versus down-weighted; report how metrics move. Large sensitivity is a finding for the limitations section.

### 15.8 Multi-region back-test protocol

#### 15.8.1 Purpose
Show the same pipeline, with no per-region configuration, run across hilly India's main physiographic settings, and report per region what held up and what did not. These are **retrospective replay back-tests**, not pilots: a pilot means a live deployment, which this document does not claim (Section 15.12.7). This is the empirical side of the claim in Section 3.3.

#### 15.8.2 Regions and candidate events

Every event below is a candidate that must be verified (date, location, documented source) before it enters a table.

| # | Region | Setting | Mechanism it stresses | Candidate events |
|---|---|---|---|---|
| 1 | Southern Western Ghats (Kerala, Kodagu) | Lateritic soils, long monsoon saturation | `SATURATION_LANDSLIDE`, `COMPOUND_CASCADE` | Wayanad 2024; Puthumala and Kavalappara 2019; Pettimudi (Idukki) 2020; Kodagu 2018 |
| 2 | Northern Western Ghats (Maharashtra, Goa) | Basaltic Deccan slopes, intense orographic rain | `SATURATION_LANDSLIDE` | Irshalwadi (Raigad) 2023; Taliye (Raigad) 2021; Malin (Pune) 2014 |
| 3 | Nilgiris–Anamalai–Palani (Tamil Nadu high ranges) | Plantation slopes, two rainy seasons | `SATURATION_LANDSLIDE` | Coonoor/Kotagiri Nov 2009; Nilgiris Aug 2019 |
| 4 | Eastern Ghats (Odisha, Andhra) | Cyclone-driven rain on lower hills | `SATURATION_FLOOD`, landslides | Gajapati (Titli cyclone) 2018; others to be sourced from SDMA |
| 5 | Himachal Pradesh | Steep valleys, road-cut slopes, monsoon and western-disturbance interaction | `CLOUDBURST_FLASH`, `SATURATION_LANDSLIDE`, `COMPOUND_CASCADE` | July–Aug 2023 (Kullu, Shimla); Kinnaur 2021 |
| 6 | Jammu & Kashmir, Ladakh | Pir Panjal and trans-Himalaya, cold-arid in the north | `CLOUDBURST_FLASH` | Leh 2010; Amarnath 2022; Kishtwar 2025 *(verify)* |
| 7 | Uttarakhand (Central Himalaya) | Steep, fractured slopes, high pilgrim exposure | `CLOUDBURST_FLASH`, `SATURATION_FLOOD` | Oct 2021 rains; Dharali (Uttarkashi) 2025 *(verify)*; Kedarnath 2013 (mixed trigger, see exclusion rule) |
| 8 | Sikkim and Darjeeling hills | Eastern Himalaya, very high rainfall, road-cut slopes | `SATURATION_LANDSLIDE` | Mirik 2015; North Sikkim June 2024; Darjeeling Oct 2025 *(verify)* |
| 9 | Arunachal Pradesh | Sparse gauges and inventory | `SATURATION_LANDSLIDE` under uncalibrated conditions | To be sourced from the state SDMA and news records |
| 10 | Mizoram, Manipur, Nagaland | Folded hills, weak sedimentary rock, human cuts | `SATURATION_LANDSLIDE` | Aizawl/Remal May 2024; Noney (Manipur) June 2022 |
| 11 | Meghalaya and Assam hills (Dima Hasao, Barak) | Heaviest rainfall in India, mixed flood and landslide | `SATURATION_FLOOD`, `COMPOUND_CASCADE` | Dima Hasao May 2022; others to be sourced |

**Exclusion rule.** Events driven by GLOF, glacier or rock-ice avalanche, or seismic triggers are out (Section 19). Kedarnath 2013 and Sikkim Oct 2023 mix in such triggers, so they are used only if a rainfall-only component can be separated, and are labeled. Otherwise they are left out.

Regions 6, 9 and 11 are deliberate stress tests: cold-arid and glacial influence, or sparse gauges and labels. Weak or absent results there are expected and are reported, because they show where confidence drops and why.

#### 15.8.3 Tiering

Running eleven regions at full depth is not realistic, so they run in tiers on an identical pipeline.

| Tier | Regions | Depth |
|---|---|---|
| **A: Headline** | 1 (S. Western Ghats), 5 (Himachal), 8 (Sikkim/Darjeeling) | Held-out + in-sample + physics-only baseline, 2–3 events each, village-level metrics |
| **B: Coverage** | 2, 3, 7, 10 | One event each: held-out run and physics-only baseline |
| **C: Stress test** | 4, 6, 9, 11 | One event each, or a replay-only run if no usable event record exists; reported as a limitation and a confidence demonstration, not a validation |

A region receives a validation claim only if it meets the minimum-data rule (Section 15.3). Otherwise it is shown as replay only.

#### 15.8.4 Runs

| Run | Training | Label |
|---|---|---|
| Held-out (primary) | Region excluded (LORO) | **Held-out** |
| In-sample (reference) | Region included | **In-sample** |
| Physics-only baseline | No ML; FS + fitted I–D threshold only | Baseline |

The held-out run is the headline. Where a region has too few events for LORO, it is shown as in-sample only and flagged, not reported as validation.

#### 15.8.5 Replay
- Rainfall and soil state are rebuilt from IMERG and ERA5-Land for T−72 to T−1 h.
- Forecast projection is replayed from archived forecasts where available, otherwise labeled perfect-foresight.
- Sensors do not exist for past events, so all runs use satellite-only input (`C_in` at its satellite tier). This tests the degraded mode, which is the honest case for most of hilly India.

#### 15.8.6 Record per event
Tier and confidence at each offset, trigger type, lead-time bucket, villages flagged, villages affected, and false alarms in the surrounding 30 days for the same region.

#### 15.8.7 Result tables (filled after execution; nothing below is a result)

**Per event**

| Event | Region | Hazard | POD | FAR | CSI | Median lead | Confidence at first Red | Village POD / FAR (Section 15.11) | Held-out / In-sample |
|---|---|---|---|---|---|---|---|---|---|
| Event 1 | Region | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| Event 2 | Region | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| … | | | | | | | | | |

**Cross-region summary**

| # | Region | Tier | Events run | Held-out POD | Held-out FAR | Physics-only POD | ML gain | Village POD / FAR | Dominant confidence limiter | `C_cal` state |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | S. Western Ghats | A | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | N. Western Ghats | B | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | Nilgiris–Anamalai | B | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 | Eastern Ghats | C | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 5 | Himachal | A | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 6 | J&K, Ladakh | C | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 7 | Uttarakhand | B | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 8 | Sikkim/Darjeeling | A | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 9 | Arunachal | C | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 10 | Mizoram/Manipur/Nagaland | B | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 11 | Meghalaya/Assam hills | C | n | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

#### 15.8.8 Reporting rules
- Report **all** events run, including misses and poor results. Choosing only good events is selection bias.
- Report event counts next to every metric. One to three events per region is an illustration, not a statistic.
- If ML does not beat the physics-only baseline in a region, say so. That finding shows where labels are too sparse.
- Expect `CLOUDBURST_FLASH` cases in the Himalaya to show short or no lead time (Section 9.4). Report that as designed, not as a failure.
- Say "pipeline run on eleven regions, validated where event data exists", never "validated in all regions".
- Frozen with the rest of the package (Section 15.9), dated.

### 15.9 Freeze package

LOEO, LORO (per region), LOCO, spatial-block, hazard split, baselines, ablations, confidence check, fitted constants (`k`, `C_in`, tier cut points, `w`, `α`), village-level metrics (Section 15.11), back-test tables and the region-agnostic pilot table (Section 15.12) are recorded and frozen together, dated, before any dashboard panel displays them. The dashboard never recomputes them. A worse later run may not silently replace an earlier one; both are kept with dates.

### 15.10 Known validation risks

Inventory-derived labels and features (circularity), unrecorded events among negatives, small fold counts, spatial autocorrelation, hindcast forecast quality versus real-time forecasts, and simulated inputs excluded from validation by design.

**Fallback headline.** If held-out ML does not beat the physics-only baseline (FS plus fitted I–D threshold) in most regions, the headline claim becomes: a physics-first, uncertainty-aware village-level system in which ML is reported as an ablation, and confidence is shown honestly. This is decided before results are seen, so a weak result changes the wording, not the evidence rules.

### 15.11 Village-level validation

Head labels are per hex or catchment (Section 8.2), so the village claim needs its own metrics.

| Item | Definition |
|---|---|
| Village hit | A recorded event whose location lies inside the footprint **or** in a source zone that the reach rule (Section 5.3.2) connects to the footprint, within the warning window |
| Village POD / FAR / CSI | Computed on village-cycles using `alert_value`, not on hex rows |
| Ablations | (a) footprint-only vs. footprint + source reach; (b) max vs. P90 aggregation; (c) with vs. without the two-cycle persistence rule |
| Alert burden | Alarms per village per season and consecutive-alarm count (Section 10.3), reported per `boundary_quality` class |
| Reporting rule | Any village-level accuracy is stated with the number of villages and events behind it |

Every event in the Section 15.8 tables also gets a village-level row.

### 15.12 Multi-region region-agnostic pilot

#### 15.12.1 What it proves, and what it does not

| Proves | Does not prove |
|---|---|
| The same code, configuration and parameters run end to end in every region with zero manual setup | Accuracy in any region (Section 15.8) |
| Failures and data gaps are handled visibly through the fallback chain, not hidden or patched per region | Live operational performance (needs sponsorship, Section 10.5) |
| Confidence reflects local data quality differently across regions | Uniform skill everywhere (Section 3.3) |

#### 15.12.2 Agnosticism rules (frozen before the run)

1. **One release.** A single tagged code version and a single configuration file, hashed and recorded before any region is run.
2. **No regional parameters.** No per-region constants, thresholds or code branches; everything regional is derived by code (design principle 6). A config diff between regions must be empty.
3. **Input is a place name or drawn boundary only.**
4. **Pre-declared locations.** Each region's pilot location is chosen and written down before any output is viewed, and is not a cached shortlist location.
5. **Failures are reported, not patched.** A region that fails gets its failure mode documented. A generic fix is allowed, but every region is then re-run on the new release (rule 6).
6. **Regression rule.** Any code change triggers a re-run of all regions. Results from different releases are never mixed.

#### 15.12.3 Procedure (per region, identical for all eleven)

```text
1  Onboard from place name         → Section 5.2 pipeline, manual interventions logged (target: 0)
2  Replay dynamic state            → one event window + one quiet window (same length, same season)
3  Run engines, heads, decision    → region held out from training (LORO) wherever Section 15.3 allows
4  Draft CAP for any Orange/Red    → held for authorization as usual
5  Record the checks below
```

#### 15.12.4 Checks and pass criteria

| # | Check | Measure | Pass criterion |
|---|---|---|---|
| A | Zero-config onboarding | Manual interventions; config diff vs. reference | 0 interventions; diff empty |
| B | Layer completeness | Layers resolved per tier (0–3, Section 6.4); `boundary_quality` mix; `footprint_approx` share | Every layer resolved at some tier with a badge; none silently defaulted |
| C | Scale and runtime | Hexes, catchments, villages; onboarding and replay time | Completes; no crash or timeout. Times are reported, not benchmarked |
| D | Physical plausibility | FS `p05/p50/p95` ranges; runoff and `qp` ranges; trigger types vs. expected mechanism | Values inside physical bounds; trigger types consistent with the event's mechanism, or `UNSPECIFIED` |
| E | Quiet-period behavior | Orange/Red drafts in the quiet window | Reported per region; not pass/fail, but any Red in a quiet window is listed as a false alarm |
| F | Confidence follows data quality | Confidence and its four factors against input tier and `C_cal` | Confidence is lower where inputs are satellite-only or uncalibrated, checked by monotonicity across regions (feeds Section 15.6) |
| G | Degradation works | Forced sensor and rainfall-layer outage in each region | Fallback tier changes, badge updates, no crash |

**Agnostic-pass definition:** a region passes when checks A, B, C and G are met. D, E and F are reported findings, not gates. A region that fails B or C is shown as failed.

#### 15.12.5 Result table (filled after execution; nothing below is a result)

| # | Region | Location (pre-declared) | Release | Manual interventions | Layers resolved | Villages / catchments | Boundary quality (official / osm / voronoi) | Onboarding time | Checks A–G | Agnostic pass |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | S. Western Ghats | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | N. Western Ghats | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | Nilgiris–Anamalai | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 | Eastern Ghats | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 5 | Himachal | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 6 | J&K, Ladakh | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 7 | Uttarakhand | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 8 | Sikkim/Darjeeling | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 9 | Arunachal | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 10 | Mizoram/Manipur/Nagaland | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 11 | Meghalaya/Assam hills | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

#### 15.12.6 Cross-region readout

One panel shows three columns per region: **agnostic pass** (this section), **accuracy status** (Section 15.8: held-out validated / replay only / no event data) and **confidence state** (`C_cal`, `C_in`). A region can be green on the first and grey on the second; that combination is the honest answer to "does it work anywhere?".

#### 15.12.7 From replay pilot to live pilot (not claimed)

A live pilot needs a sponsoring State SDMA or district authority, real nodes with a named custodian (Section 12.4), and a season of shadow-mode operation with alerts drafted but never sent. That belongs to Roadmap Phase 5. This section claims replay only.

---

## 16. Demo plan and fallback strategy

### 16.1 Script

1. Type any hilly place name (a judge's choice, not just the shortlist). Onboarding resolves boundary, catchments, villages and shows per-layer badges.
2. If the soil raster was not pre-fetched, the system says so and runs terrain-only with reduced confidence.
3. Map renders hexes, catchments and village chips; toggle Flood / Landslide / Compound; open a village: trigger type, lead-time bucket, four-factor confidence with reasons.
4. Show sensor-adjusted FS on the hex with a node (real, replay or simulated, labeled); show the suggested next sensor sites.
5. Replay a historical event (back-test view) with the scrubber. A region switcher loads one event per region; each shows held-out results first, the in-sample label, and the physics-only comparison.
6. An Orange/Red draft appears as a popup on that region's chip (what is happening, what to do, confidence, nearest shelter) and as a pending CAP alert; perform the two-person authorization and show the dispatch-readiness state (Section 16.3).
7. Kill one sensor stream live: fallback tier changes, badge updates, no crash.
8. Show the shelter/route advisory with a blocked segment excluded.
9. Show the frozen validation panel, with per-region LORO first.
10. Show the multi-region pilot table: agnostic pass, accuracy status and confidence state for all eleven regions (Section 15.12.6).

### 16.2 Resilience

- Live fetch is always attempted first; the cached shortlist (5–10 locations across Himalaya, Western Ghats and Northeast) is insurance, not scope. Replay inputs for the Tier A back-test events (Section 15.8.3) are cached the same way; Tier B and C load on demand.
- Fallbacks appear as visible badges, turning a network failure into a demonstration.
- Per-hex independent fallback, concurrency limits, deduplicated dynamic calls, snapshot-then-delta reconnect, cold-start guard.
- Pre-demo checklist: one refresh cycle at a time; kill-network test; forced disconnect/reconnect; one genuinely novel, non-shortlist location tested live; historical replay checked by hand.

### 16.3 Live-operations demo (simulated feed)

The demo shows the operational workflow: detection, a drafted alert, human authorization and dispatch readiness. It does not show live operational performance, which needs a sponsored shadow-mode season (Section 15.12.7).

| Element | Behavior |
|---|---|
| Region strip | One chip per region, coloured by its worst active tier, with a word label; clicking a region with no alert fires a labelled demo alert for it |
| Alert popup | Tier, village, hazard; **what is happening** (trigger type and one-line reason); **what to do** (actions by trigger type, Section 10.4); lead-time bucket; nearest shelter; the four confidence factors |
| Authorization | Pending 0/2 → two different people in two roles (duty officer, district authority) → Authorized. The backend rejects the same person or role twice |
| Dispatch state | CAP built (`status=Exercise`), Cell Broadcast ready but not published, edge siren and caretaker SMS rules armed |
| Labeling | Permanent banner: "Simulated feed. Exercise alert, nothing is being sent." |

Feed source: the replayed back-test and pilot events (Sections 15.8, 15.12), passed through the real pipeline where built, and simulated scenarios otherwise, always labeled. The prototype modules are `live_alerts.py` (FastAPI WebSocket feed and authorization) and `AlertConsole.jsx` (region strip and popup).

---

## 17. Build plan and MVP scope

Stages are ordered by dependency, not by calendar. Effort is a rough relative sizing (S under half a day, M one to two days, L three or more) for a small team and should be mapped to the real schedule.

| Stage | Deliverable | Effort | Gate / milestone |
|---|---|---|---|
| 0 | Data-access lockdown: Tier-1 sources reachable; SoilGrids bulk rasters pre-fetched for the shortlist; API terms checked | S | Rasters on disk before Stage 1 |
| 1 | Onboarding: boundary, DEM, terrain, **catchments, villages/wards**, land cover, soil params, H3, history check, siting ranking | L | A never-tested place name yields a full static table with zero manual config |
| 2 | Dynamic layer: rainfall merge + downscaling, soil state, single fallback chain | M | Per-layer badges; fallback tested |
| 3 | Engines: E2 (FS with soil + depth Monte-Carlo, I–D fit), E3 (SCS-CN, Tc, peak, HAND inundation), E4 (if stage sensors), classifier | M–L | FS and runoff sane on one documented real event, checked by hand |
| 4 | Dataset: pooled inventory, negative sampling, temporal offsets, two heads, 32 features | M | Provenance (event, region, offset) preserved per row |
| 5 | **Validation gate**: LOEO, LORO (per region), LOCO, spatial block, baselines, ablations, confidence fit, multi-region back-test (Section 15.8) | L | Results frozen; go/no-go for any accuracy claim |
| 5b | **Region-agnostic pilot** (Section 15.12): one command runs all regions on one frozen release and writes the pilot table | M | Zero manual interventions; table frozen |
| 6 | Decision engine, village roll-up, CAP + authorization, exposure/priority, evacuation advisory | M | Full cycle runs backend-only |
| 7 | IoT: 1–2 real or replay nodes, MQTT ingest, QC, snapping, edge rules, simulated fleet | M | Sensor-adjusted hex demonstrably differs from gridded one |
| 8 | Dashboard, village table, degraded mode, validation panel; usability test | M | Live vs cached badges correct; test run |
| 9 | Demo readiness checklist (Section 16.2) | S | Novel-location live test passes |

### MVP cut

| Must build | Should build | Simulate (labeled) | Future |
|---|---|---|---|
| Onboarding with catchments and villages; FS + MC uncertainty; SCS-CN flood engine; classifier; two heads; confidence (four factors); CAP draft + authorization; dashboard; validation on available events | E4 with stage sensors; sensor-siting ranking; evacuation advisory; 1–2 real or replay nodes | Most IoT nodes; SAsiaFFGS/GSI operational feeds; SACHET publishing | GLOF module; seismic debris-flow sensing; LSTM/GNN nowcast; dynamic evacuation routing; calibrated impact model |

A working slice with two engines (E2, E3) end to end and a real back-test beats six engines mocked; the MVP is scoped accordingly.

---

## 18. Limitations

One consolidated list, grouped by how they can be handled.

**Structural (not fixable within the project)**
- Limited geographic generalization: a region with no event data has less validated confidence behind it, and this narrows only as data accumulates over years.
- Pedotransfer correlations were developed largely on temperate soils; Indian laterite and residual soils may deviate. FS is an index with a band, not a design value.

**Mitigated by design, not eliminated**
- Forecast uncertainty grows with horizon and is worst for convective rainfall, so cloudburst lead time is small or absent; carried through as lead-time buckets and confidence.
- Rainfall downscaling gives a terrain-informed ~1 km field with uncertainty, not measured village rainfall.
- Hex/catchment discretization: a village can straddle units; both values are shown.
- Degree-of-saturation-to-water-table equivalence and SCS-CN are screening simplifications.
- Small pooled event dataset and unrecorded events among negatives; handled by validation design and sampling rules, not made larger.
- Labels and the `gsi_susceptibility_class` feature share an inventory origin; reported with and without.
- Village output has coarser effective input resolution than its reporting unit; landslide runout uses a reach-angle approximation; boundaries and footprints are approximate for many hill villages.
- Suction cohesion decays linearly with saturation, a screening simplification; laterite parameter ranges are literature-derived until checked against local data.
- Capacitive soil sensors drift with temperature, salinity and contact loss; managed by calibration, QC and fallback, not eliminated.

**Scoped out deliberately**
- Not a hydrodynamic model; inundation is screening-grade.
- Exposure and vulnerability are ranking indices, not loss estimates.
- Evacuation is an advisory over static shelter data.
- GLOF and seismic debris-flow sensing are future scope.
- Deep-seated and slow-moving slope failures are out of scope for the infinite-slope engine.

**Disclosed by labeling**
- Simulated sensors and operational feeds are always marked simulated; simulated inputs are excluded from model features and validation.
- The alert path is a technical-readiness demonstration until a recognized agency sponsors integration.
- Data-source terms may restrict production use (Section 6.5).
- The multi-region replay pilot demonstrates zero-config operation, not operational readiness; the live-operations demo runs on a simulated feed.
- Cross-region results rest on a small number of events per region, and several regions (for example Arunachal, J&K and Ladakh, Meghalaya and Assam hills) may have few or no documented events.

**Evidence still to be produced** — event counts, back-test metrics, fitted constants, usability results, cost quotes (Appendix E). Until then the corresponding claims are stated as design intent, not results.

---

## 19. Roadmap

| Phase | Content |
|---|---|
| 1 (this document) | Onboarding, engines E1–E4, two-head ML, four-factor confidence, CAP with authorization, village-level dashboard, edge tier, validation package |
| 2 — Research and exposure | AHP and MaxEnt comparisons, extended RF study, Sentinel-1 change-detection validation (independent of the inventory), WorldPop/OSM exposure calibrated against past impacts, dynamic evacuation routing |
| 3 — Advanced prediction | LSTM/GRU/GNN nowcasting once event counts justify it, probabilistic forecasting, higher-resolution soil moisture, real sensor deployment at scale; Sentinel-1 PS-InSAR persistent-scatterer monitoring for slow, deep-seated deformation; GPU-accelerated 2D shallow-water solvers run only on Orange/Red catchments (HAND remains the fast screen) |
| 4 — Cascading and additional mechanisms | Explicit dependency chain (rain → runoff and saturation → landslide → blockage → surge → evacuation delay), GLOF module, seismic debris-flow sensing |
| 5 — Operationalization | Data-sharing agreements (IMD, GSI, CWC), sponsored SACHET/Cell Broadcast integration, continuous validation with periodic freezes, community feedback loop and federated learning across states; a shadow-mode live pilot in one or two districts with a sponsoring SDMA (alerts drafted, never sent, for a full season) |

As real event data arrives for more regions, `C_cal` reaches 1.0 for more of hilly India and the confidence gap between calibrated and uncalibrated regions should shrink; Section 15.6 is the check that shows whether it does.

---

## Appendix A — Fix traceability

| ID | Fix | Where applied |
|---|---|---|
| A1 | Cut MVP to E1–E4; GLOF and seismic sensing to future | 1, 7, 17, 19 |
| A2 | Rainfall downscaling method with uncertainty bands | 6.3 |
| A3 | Rule-based trigger classifier (no ML claimed) | 7.5 |
| A4 | Fusion specified: learned heads, no hand-set weights | 8.2 |
| A5 | Thresholds derived from inventory; edge thresholds calibrated | 7.2.3, 12.2 |
| A6 | Conceptual runoff model first (SCS-CN, Tc); ML residual later | 7.3 |
| A7 | Validation design (LOEO/LORO/LOCO/spatial, POD/FAR/CSI/Brier) | 15 |
| A8 | Confidence computed from data coverage, model and engine uncertainty | 9.2 |
| A9 | CAP, authorization, hysteresis, cold-start, sponsorship note | 10 |
| A10 | Exposure and vulnerability sources named | 11.1 |
| A11 | Evacuation MVP (shelter mapping, blockage-aware advisory) | 11.2 |
| A12 | Sensor economics, ownership, upkeep | 12.4 |
| A13 | Sensor-siting ranking | 12.3 |
| A14 | Demo script, degraded mode, role-based UX | 13, 16 |
| B1 | Confidence breakdown reconciled with headline number | 9.2, 14.2 |
| B2 | Per-hazard heads and outputs defined | 8.2 |
| B3 | Hour-resolution lead-time buckets; T−3/T−1 training offsets | 8.5, 9.4 |
| B4 | Single fallback chain; ERA5 removed from live tiers | 6.4 |
| B5 | Document hygiene: no stale markers or external-version references; one limitations section | whole document, 18 |
| B6 | `has_local_calibration` removed from model features | 8.3 |
| B7 | Confidence checked against accuracy, not by construction | 15.6 |
| B8 | Negative-sampling scheme specified, with sensitivity | 8.4, 15.7 |
| B9 | Soil depth and roots in FS uncertainty | 7.2.2 |
| B10 | Tier cut points reset from reliability diagram per data tier | 9.1, 15.9 |
| B11 | IoT soil moisture drives saturation term in FS | 7.2.1, 12.2 |
| B12 | Catchment flood module and specified inundation method | 7.3 |
| B13 | Hex/catchment→village/ward mapping | 5.3 |
| B14 | Offline-first tier standard | 10.6 |
| B15 | Evidence plan and back-test protocol; **results pending** | 15.8, Appendix E |
| B16 | API and data terms-of-use checks | 6.5 |
| B17 | Summary and slide outline; **slides not yet built** | 1, Appendix D |
| B18 | Usability protocol; **test pending** | 13.5, Appendix E |

**Additional issues fixed during the merge:** simulated guidance signals removed from model features (Section 8.3); confidence's second term generalized so the flood head has a defined equivalent of the FS penalty (Section 9.2); ERA5-Land restricted to training and replay (Section 6.4).

---

## Appendix B — CAP example (illustrative, drafted and held for authorization)

```xml
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>HYDRASENSE-{region_code}-000123</identifier>
  <sender>hydrasense (draft, not published)</sender>
  <sent>2026-09-27T14:32:00+05:30</sent>
  <status>Exercise</status>
  <msgType>Alert</msgType>
  <scope>Restricted</scope>
  <info>
    <category>Geo</category><category>Met</category>
    <event>Landslide risk (saturation-triggered)</event>
    <urgency>Expected</urgency><severity>Severe</severity><certainty>Possible</certainty>
    <headline>Landslide risk RED in {village_names}: move away from steep slopes</headline>
    <description>Projected lead time 3–6 h. No local historical event record exists for this
      area, so the estimate is physics-derived with reduced confidence (53/100).</description>
    <parameter><valueName>trigger_type</valueName><value>SATURATION_LANDSLIDE</value></parameter>
    <parameter><valueName>confidence_score</valueName><value>53</value></parameter>
    <parameter><valueName>confidence_factors</valueName>
      <value>model=91;engine=77;calibration=75;input=100</value></parameter>
    <parameter><valueName>has_local_calibration</valueName><value>false</value></parameter>
    <parameter><valueName>lead_time_bucket</valueName><value>3-6 h</value></parameter>
    <parameter><valueName>alert_driver</valueName><value>upslope_source</value></parameter>
    <parameter><valueName>boundary_quality</valueName><value>osm</value></parameter>
    <parameter><valueName>data_source_quality</valueName>
      <value>terrain: live; soil: cached; rainfall: live; sensor: none</value></parameter>
    <area><areaDesc>{village_names}</areaDesc><polygon>…</polygon></area>
  </info>
</alert>
```

## Appendix C — Design FAQ

**Is this a replacement for SAsiaFFGS or GSI?** No. It downscales and fuses their guidance to village level.

**Is it really region-agnostic?** The pipeline runs identically anywhere with no manual setup. Accuracy is validated only where events exist, and the system shows per-region calibration status at prediction time.

**How is "hyper-local" justified when rainfall is ~10 km?** Through gauge-anchored merging and terrain adjustment to ~1 km with an uncertainty layer (Section 6.3), fused with 30 m terrain and 250 m soil. Sub-kilometre rainfall skill is not claimed.

**Why both flood and landslide?** They share rainfall and saturation drivers and often cascade; two heads keep them separately measurable, and the classifier names the mechanism.

**Why physics plus ML?** Physics supplies a stability signal and uncertainty that sparse labels could not teach; ML fuses it with terrain, rainfall and runoff.

**How do sensors help if only a few exist?** They override gridded inputs locally, anchor rainfall, and drive edge alarms; siting ranking shows where more would matter most.

**Can it warn for a cloudburst?** Only with short lead time, and only where a nowcast, upstream stage rise or local sensor sees it. Otherwise it says so and relies on the edge tier.

**Is confidence a probability?** No. It is an engineered data-coverage and uncertainty index, fitted against observed accuracy and shown with its four factors.

**Do you auto-publish alerts?** No. Every Orange/Red alert is drafted and held for two-person authorization, and live SACHET publishing needs institutional sponsorship.

**Is the village-level warning accurate?** It is reported at village level, built from terrain-local physics and any local sensor. Rainfall skill is about 1 km, and that uncertainty is shown per village. Village-level POD and FAR are reported separately (Section 15.11).

**Does it work in all regions?** The pipeline runs unchanged in eleven hilly regions with no manual setup (Section 15.12). Accuracy is validated only where event data exists, and each region's status is shown (Section 15.8).

**What is still unproven?** Everything listed in Appendix E.

## Appendix D — 10-slide pitch outline

1. **Problem:** hilly India, short warning times, coarse or siloed systems.
2. **Gap:** no system gives village-level, flood-plus-landslide, any-terrain warning.
3. **Solution in one line** and the four moves (resolve, model mechanism, snap to sensors, governed alerts).
4. **Architecture** (the layered diagram, Section 4).
5. **Autonomous onboarding** with catchments, villages and sensor siting; runs unchanged across 11 regions; live demo cue.
6. **Physics and catchment engines:** FS with soil+depth uncertainty, SCS-CN flood, trigger types.
7. **Sensors and edge tier:** sensor-snapping, offline alerting, economics and siting.
8. **Honest confidence:** four factors, same risk with different confidence, per-region calibration.
9. **Evidence:** multi-region back-test across 11 regions (held-out LORO by tier, baselines, village-level metrics), plus the region-agnostic pilot table (fill with real numbers).
10. **Impact and roadmap:** deployment path (SDMA sponsorship), exposure/evacuation, future mechanisms.

## Appendix E — Open items that need real numbers

| Item | Needed to complete | Status |
|---|---|---|
| Pooled event counts (per region, per hazard) | Compile inventory | Not produced |
| LOEO / LORO / LOCO / spatial-block results | Run Stage 5 | Not produced |
| Baseline and ablation comparisons | Run Stage 5 | Not produced |
| Multi-region back-test tables (Section 15.8.7) | Run Section 15.8 | Not produced |
| Event compilation for all 11 regions (date, location, source) | Compile and verify candidate events | Not done |
| Region-agnostic pilot table and pre-declared pilot locations (Section 15.12) | Run the pilot | Not produced |
| Village-level metrics (Section 15.11) | Run with the back-tests | Not produced |
| Fitted constants: `k`, `C_in` levels, widening `w`, tier cut points, I–D thresholds, reach angle `α`, source-slope cutoff, P90 choice, persistence N, `c_s0` bounds | Fit from validation | Provisional values only |
| Cell Broadcast page length, encoding and language rules | Check current specification | Not verified |
| Laterite/residual-soil parameter ranges and per-node sensor calibration constants | Literature review; gravimetric calibration | Not done |
| Blockage-check and classifier thresholds | Tune in back-test | Initial values only |
| Field-grade node, gateway and comms cost quotes | Vendor quotes | Not obtained |
| Usability results (completion time, SUS) | Run Section 13.5 | Not run |
| API and data terms verification | Check Section 6.5 items | Not verified |
| Re-verification of Section 3.1 table and channel-status claims | Check current sources | Not verified |
| 10-slide deck | Build from Appendix D | Not built |

## Appendix F — Revision log (R1)

| Area | Change | Where applied |
|---|---|---|
| Sensors | Soil temperature probe, temperature compensation, salinity and air-gap flags, independent cross-checks, per-node gravimetric calibration | 12.1, 12.2, 12.4 |
| Physics | Matric-suction cohesion `c_s(m)`, laterite class flag, `c_s0` sampled in Monte-Carlo | 5.2, 7.2 |
| Classifier | Shared saturation boundary (`m = 0.7`), no gap to `UNSPECIFIED` | 7.5 |
| Explainability | SHAP promoted to must-build | 8.6, 14.4 |
| Alerting | Cell Broadcast short template, CAP 1.2 / ITU-T X.1303 citation, SMS vs. Cell Broadcast comparison | 10.2, 10.5 |
| Scope | Deep-seated failures out of scope; PS-InSAR and 2D shallow-water on roadmap | 3.2, 18, 19 |
| Data | Supplementary event sources beyond Bhukosh; fallback headline claim | 6.6, 15.10 |
| Positioning | Method and local-sensor columns, HydraSense row | 3.1 |
| Village level | Rewritten mapping: boundary quality, P90 footprint, upslope source reach, catchment-anchored flood, persistence; village record | 5.3, 9.3, 9.6, 10.2, 14.2 |
| Village validation | Village-level POD/FAR/CSI and ablations | 15.11 |
| Multi-region validation | Eleven regions, tiers A/B/C, held-out and physics-only runs, reporting rules | 15.8 |
| Region-agnostic pilot | Zero-config replay pilot, checks A–G, frozen release | 15.12, 17 (stage 5b) |
| Live-operations demo | Simulated feed, alert popup, two-person authorization, dispatch readiness | 16.1, 16.3 |
| Claims | Village-scale rainfall skill and validated-everywhere claims stated as No | 3.3, 15.8.8, Appendix C |
| Open items | New rows for events, pilot, village metrics, constants, broadcast limits | Appendix E |
