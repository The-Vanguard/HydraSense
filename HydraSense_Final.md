# HydraSense — Final Architecture Document

**Subtitle:** A Region-Agnostic Hyper-Local Flash Flood & Landslide Early Warning System for Hilly India
**Prepared for:** Smart India Hackathon — Flash Flood Prediction System for Hilly Regions using Multi-Source Data

> **Document Status:** All 20 sections are drafted. This remains open to correction — as Sections 8.6 and 9 already demonstrate internally, a figure or formula caught wrong in a later section gets fixed at its source, not silently left inconsistent.

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [What HydraSense Is — and Is Not](#3-what-hydrasense-is--and-is-not)
4. [Relationship With Existing Indian Systems](#4-relationship-with-existing-indian-systems)
5. [Research Gap / Differentiation](#5-research-gap--differentiation)
6. [Core Architecture — Autonomous Region Onboarding Pipeline](#6-core-architecture--autonomous-region-onboarding-pipeline)
7. [Feasibility & Design Trade-offs](#7-feasibility--design-trade-offs)
8. [Data Layer](#8-data-layer)
9. [Physics Layer — Factor of Safety](#9-physics-layer--factor-of-safety)
10. [Machine Learning Fusion Layer](#10-machine-learning-fusion-layer)
11. [Decision Engine — Risk, Confidence, Lead Time](#11-decision-engine--risk-confidence-lead-time)
12. [Alert Architecture](#12-alert-architecture)
13. [Dashboard & UI/UX](#13-dashboard--uiux)
14. [Live Demo Flow & Fallback Strategy](#14-live-demo-flow--fallback-strategy)
15. [Technical Stack](#15-technical-stack)
16. [Build Plan & Milestones](#16-build-plan--milestones)
17. [Validation Strategy](#17-validation-strategy)
18. [Scientific Limitations](#18-scientific-limitations)
19. [Future Roadmap](#19-future-roadmap)
20. [Appendices](#20-appendices)

---

## 1. Executive Summary

Hilly regions of India face flash floods and rainfall-triggered landslides with very short warning times. Existing systems — SAsiaFFGS, GSI's National Landslide Forecasting Centre, CWC's gauge network, C-FLOOD, IMD's MHEW-DSS, and ISRO/NRSC's satellite monitoring — each solve one slice of this problem, but none resolves risk to village/ward granularity across arbitrary hill terrain, fuses flood and landslide hazard together, or targets the small, steep, largely ungauged micro-catchments that structurally fall outside all of their coverage.

HydraSense is a last-mile downscaling and decision layer that converts terrain, rainfall, soil state, and historical context into hyper-local, H3-hexagon-resolved risk — for **any hilly region in India**, not a pre-selected pilot site. It does this through an **Autonomous Region Onboarding Pipeline**: given a place name or a drawn boundary, the system resolves terrain, land cover, and geotechnical soil parameters entirely from global, automatically-queryable data sources, requiring no manual per-region curation. Where local historical event data exists (e.g. GSI-mapped districts), it is ingested and improves confidence. Where it doesn't, the system still produces a physically-grounded estimate — with confidence explicitly lowered to reflect the absence of local calibration, rather than silently presenting every region as equally certain.

> **Core design principle:** the architecture is genuinely region-agnostic; empirical validation accuracy is necessarily uneven across regions, and the system says so out loud, per-region, in real time. This is the core design principle that separates HydraSense's claim from an overreach.

---

## 2. Problem Statement

### The operational challenge

> **Which local area is becoming dangerous, how confident are we, and how much time is available before the risk reaches an action threshold — anywhere in hilly India, not only at a handful of instrumented or pre-studied sites?**

### Objective

For any queried hilly location, produce a hyper-local risk estimate per H3 cell and translate it into:

1. Risk score (0–100)
2. Hazard tier (Green / Yellow / Orange / Red)
3. Confidence score, explicitly reflecting local data availability
4. Estimated time-to-RED (forecast-derived lead time)
5. Affected area
6. Simplified inundation visualization
7. Nearest known shelter (where shelter data exists for the region)
8. Standardized, CAP-compliant emergency alert

---

## 3. What HydraSense Is — and Is Not

### It is

- A last-mile downscaling layer over existing national guidance (SAsiaFFGS, GSI, IMD)
- A multi-source data-fusion system operating on globally-available inputs, not a single proprietary dataset
- A flash-flood + landslide multi-hazard system
- A physics + ML hybrid architecture
- An autonomous, region-agnostic onboarding pipeline — no manual per-region configuration step
- A confidence-aware decision-support system that reports where its confidence is high (locally calibrated) versus low (extrapolated)
- An alert-generation layer, CAP/SACHET-compatible by design

### It is not

- A replacement for SAsiaFFGS, GSI's operational forecasting, or CWC's gauge network
- A claim of uniform empirical accuracy across every hill region in India — this is explicitly distinguished from architectural region-agnosticism (see Section 7)
- A full hydrodynamic flood simulator, a full evacuation-routing platform, or a full exposure/impact model in this phase
- A live, sponsored integration into GSI's or IMD's operational data feeds (simulated adapters, clearly labeled, stand in for these until institutional access exists)
- A real national-scale physical IoT sensor deployment (software-simulated for this phase)

### The claim to make, precisely

> "HydraSense is a last-mile downscaling and decision layer that converts broader flash-flood and landslide guidance into hyper-local, H3-based risk for any hilly region in India, using automatically-derived terrain and geotechnical parameters, physics-based slope stability, historical context where available, and forecast-derived time-to-threshold — with confidence that honestly reflects how much local data actually backs each estimate."

---

## 4. Relationship With Existing Indian Systems

*(Carried forward from the original architecture analysis — this section's substance does not change under the region-agnostic redesign; it is restated here for completeness.)*

| System | Hazard covered | Spatial unit | Lead time | Core method | Structural gap vs. this problem statement |
|---|---|---|---|---|---|
| SAsiaFFGS | Flash flood only | 4 km × 4 km watershed grid | 6–24 h | Hydrologic FFG model + NWP | Too coarse to identify which village within a watershed |
| GSI NLFC / Bhusanket | Landslide only | District bulletin | Daily / short-range | Susceptibility + rainfall | District-scale, only ~21 districts mapped so far, no flood component |
| CWC Flood Forecasting | River flood only | Named gauge points | Hours (basin travel time) | Rainfall-runoff / routing | Sparse instrumentation in small, steep hill catchments |
| C-FLOOD | River flood only | Village (inside covered basins) | 2 days | 2-D hydrodynamic (needs channel geometry) | Only 3 large lowland/mid-course basins; no hill catchments, no landslide |
| IMD MHEW-DSS | Generic weather hazards | District / block | Hours–days | Radar + ensemble NWP | Meteorological only — no hydrology, no slope-stability physics |
| SACHET | None (dissemination only) | State / district CAP polygons | N/A | N/A | Not a predictor; only recognized agencies can publish |
| ISRO / NRSC | Flood (mostly post-event) + landslide (road corridors) | Corridor lines / satellite scenes | Mostly post-event; 2-day for 2 basins | SAR/optical mapping, rainfall threshold | Reactive monitoring, not fused hyper-local forward prediction |

**The actual gap, stated precisely:** no existing Indian system simultaneously (1) resolves risk to village/ward granularity in hilly terrain, (2) fuses flood and landslide hazard on shared physical drivers, and (3) does so for terrain that hasn't been specifically pre-mapped or pre-instrumented — which is the majority of hilly India outside GSI's ~21 pilot districts and CWC's sparse hill-state gauge network.

**Recommended positioning:** HydraSense as the missing hyper-local fusion layer that consumes upstream guidance (MHEW-DSS/IMD rainfall, GSI susceptibility where mapped) and, once sponsored, could push hex-level CAP-compliant output toward NDEM/SACHET — not a stand-alone replacement system.

---

## 5. Research Gap / Differentiation

HydraSense does not claim novelty merely because it uses AI. The differentiators, stated as candidates pending experimental demonstration, not proven facts:

1. **Autonomous region onboarding** — terrain, land cover, and geotechnical parameters resolved automatically for any coordinate, with no manual per-region curation step. This is the sharpest differentiator versus GSI's district-by-district manual mapping approach.
2. **Multi-source local fusion** — national/regional guidance + satellite/forecast rainfall + terrain + soil + history (where available) + physics + IoT, harmonized at H3 scale.
3. **Physics + ML fusion** — the ML layer receives a physically meaningful slope-stability signal (Factor of Safety), not just raw terrain covariates.
4. **Explicit, three-factor confidence** — model-probability skew, geotechnical/FS uncertainty width, and regional historical-calibration availability, combined into one score that is honest about where the system knows less.
5. **Algorithmic lead time** — forecast-derived time-to-RED via forward projection and re-scoring, not a manually typed number.
6. **Direct risk-to-alert workflow** — CAP-compliant output generated automatically from the risk tier, not a separate manual bulletin-writing step.

---

## 6. Core Architecture — Autonomous Region Onboarding Pipeline

This section replaces the earlier "Region Configuration Layer + manual geotechnical lookup table" design. **The principle: a region is not configured, it is resolved at request time.**

```text
Input: place name OR drawn boundary
                ↓
    1. Boundary resolution (geocoding / polygon)
                ↓
    2. DEM fetch (SRTM / Copernicus GLO-30, any coordinate)
                ↓
    3. Terrain derivatives (slope, aspect, TWI, HAND,
       flow accumulation, drainage density) — computed on the fly
                ↓
    4. Land cover fetch (ESA WorldCover, global)
                ↓
    5. Geotechnical parameter derivation (SoilGrids texture/bulk
       density → cohesion & friction angle via pedotransfer
       correlations; SoilGrids' own prediction uncertainty feeds
       the FS uncertainty band) — fetched as a bulk raster via
       WCS or Google Earth Engine for the region's bounding box,
       NOT via a live per-coordinate REST call (see 7.3 note)
                ↓
    6. H3 grid generation over resolved boundary
                ↓
    7. Dynamic layer (ERA5-Land / SMAP historical state,
       Open-Meteo forecast rainfall)
                ↓
    8. Historical-context check: does this region overlap
       GSI-mapped districts / known event inventories?
        ├── YES → ingest, boosts confidence
        └── NO  → flag "no local calibration," confidence
                  reduced accordingly — not hidden
                ↓
    9. Physics FS (auto-derived parameters + SoilGrids uncertainty)
                ↓
   10. ML fusion (pooled model, trained once on all available
       historical events, scored using only features that are
       computable for any location by construction)
                ↓
   11. Output: risk, confidence, lead time per hex — with
       source/quality badges per layer
```

### Why this is genuinely region-agnostic, not just portable

A configuration-file approach (swap a YAML per region) is portable — no code rewrite needed, but a human still has to research and enter that region's parameters first. The pipeline above requires **zero human curation step** for any new region: SRTM, ESA WorldCover, SoilGrids, ERA5-Land, SMAP, and Open-Meteo are all globally queryable by coordinate. The only thing that varies by region is how much historical calibration data exists — and that variability is reported, not hidden.

### What this deliberately does not claim

This architecture does not claim the model is equally accurate in a region with zero historical events as in one with rich GSI-mapped history. It claims the system will run, and produce a physically-grounded, honestly-uncertain estimate, anywhere. Section 7 below states this distinction explicitly, because it is the load-bearing honesty claim of the whole redesign.

---

## 7. Feasibility & Design Trade-offs

### 7.1 Two different claims — do not conflate them

| Claim | Achievable? | Basis |
|---|---|---|
| Architecturally region-agnostic (no manual setup, runs anywhere) | Yes | Every input in Section 6's pipeline is a globally-queryable, automatically-derived source |
| Empirically validated accuracy everywhere in hilly India | No — for any team, not just this one | Requires labeled historical event data per region; even GSI, with a national mandate and a 91,000-event inventory, targets full national coverage only by 2030 |

The final document states both, explicitly, side by side — this is what makes the region-agnostic claim credible rather than an overreach a judge could puncture in one question.

### 7.2 Known scientific caveat: SoilGrids-derived geotechnical parameters

Pedotransfer correlations (soil texture → cohesion/friction angle) are a legitimate engineering-grade screening estimate, but the standard correlation tables were largely developed for temperate soils. Indian hill terrain frequently has laterite and deeply weathered residual soils whose strength behavior does not map cleanly onto those tables. This is stated as an explicit limitation, not glossed over — and it is the primary reason the FS output is already treated as an index with an uncertainty band rather than a precise geotechnical design value. In regions with no local historical calibration, this uncertainty band is deliberately widened.

### 7.3 Live-data risk during demonstration

Fetching DEM/SoilGrids/Open-Meteo/Nominatim live, on stage, from an arbitrary judge-chosen location, is architecturally correct but operationally risky (venue connectivity is a known hackathon failure mode). Mitigation:

- A curated shortlist of ~5–10 pre-tested locations spanning different physiographic zones (Himalayan, Western Ghats, Northeast) with cached results as guaranteed fallback.
- The live fetch is always attempted first, for the layers that actually support live per-coordinate queries (DEM via OpenTopography, forecast via Open-Meteo, geocoding via Nominatim); the fallback path is not hidden when triggered — it is displayed using the same source/quality badge system the architecture already requires (Section 6, step 11), turning a potential failure into a visible demonstration of the system's own fallback-hierarchy design.
- Compute is bounded to a fixed radius (e.g. ~15 km) around any query point, keeping terrain-derivative computation fast regardless of what is queried.
- **Verified correction** — SoilGrids is not a live-per-query layer. As of this writing, ISRIC's SoilGrids REST point-query API is officially paused with no published restoration date (confirmed directly from ISRIC's own status notice, not assumed). The soil/geotechnical layer must therefore be fetched as a bulk raster via WCS or Google Earth Engine, per region bounding box, ahead of time — not queried live per coordinate during the demo. Practically, this means: for the curated shortlist of demo locations, SoilGrids-derived geotechnical rasters are pre-fetched and cached exactly like the DEM/land-cover layers; for a genuinely novel judge-chosen location outside that shortlist, the system should honestly report "soil parameters unavailable for live fetch — physics layer running on terrain-only estimate, confidence reduced accordingly" rather than silently failing or faking a value. This is a stronger, more specific version of the general fallback principle above, driven by a real current outage rather than a hypothetical one.

### 7.4 The honest timeline trade-off

The autonomous onboarding architecture is more defensible than a single/dual pilot-region design, but it is not less work — generic bounding-box handling, multi-terrain edge cases (coastal transitions, unusually flat sub-regions), and the caching/fallback layer above all add real build time versus a hardcoded pilot. This is recorded here as a stated design decision: the harder, more honest architecture was chosen deliberately, and the fallback strategy in 7.3 is how it stays tractable on a real build timeline.

### 7.5 Overall feasibility verdict

Feasible across data sourcing, physics, ML, and alerting, **conditional** on the two mitigations above being built in from the start (not retrofitted): the SoilGrids limitation stated in the document, and the cache/fallback layer wrapping every live external call.

---

## 8. Data Layer

### 8.1 Data sourcing principles

- **Prefer authoritative Indian sources for the production narrative; prefer verifiably-accessible global sources for the working build.** These are not the same list, and the document says so explicitly rather than presenting one as if it were the other. IMD, GSI, and ISRO/NRSC products are the intended production-grade sources; SRTM, ESA WorldCover, SoilGrids, ERA5-Land, and Open-Meteo are what the working system actually queries today, chosen because they are verifiably live and globally scriptable.
- **Multi-resolution fusion, not uniform-resolution pretense.** A fine H3 output grid does not imply every input is observed at H3 resolution. Terrain is ~30m; soil is 250m; regional rainfall reanalysis can be ~9–11km. The system fuses these honestly rather than acting as if a single hyper-local dataset exists for every layer.
- **Separate raw observations from derived features.** Terrain derivatives, H3 cells, rainfall accumulations, FS indicators, and risk scores are computed by HydraSense — they are not independent external datasets and must not be presented as such.
- **Attach source/quality metadata to every prediction.** A prediction produced with cached or fallback data must be visibly distinguishable from one backed by a healthy live fetch or local historical calibration.
- **Never use information unavailable at prediction time.** Training features must satisfy `feature_timestamp <= prediction_timestamp` — a hard rule to prevent temporal leakage during historical validation.

### 8.2 Data availability matrix (region-agnostic version)

| Layer | Primary source | Access method | Resolution | Live per-query? | Role |
|---|---|---|---|---|---|
| DEM | SRTM / Copernicus GLO-30 | OpenTopography API | ~30m | Yes | Core static terrain |
| Terrain derivatives (slope, TWI, HAND, flow acc., drainage density) | Computed from DEM | Local processing (richdem/whitebox) | DEM-derived | Yes (compute, not fetch) | Core static |
| Land cover | ESA WorldCover | Direct S3/Copernicus fetch | 10m | Yes | Core static |
| Geotechnical parameters (cohesion, friction angle) | SoilGrids (ISRIC) | WCS or Google Earth Engine bulk fetch, per bounding box — REST point-query API is currently non-functional (verified, Section 7.3) | 250m | No — bulk pre-fetch only | Core FS input |
| Historical rainfall / reanalysis | ERA5-Land | Copernicus CDS API | ~9–11km | Yes (scriptable, not instant) | Core dynamic |
| Forecast rainfall | Open-Meteo | Direct REST, no key | ~9–11km for India (Open-Meteo's sub-2km regional models — ICON-D2, HRRR, AROME — cover only Europe/North America; India resolves to the global-model tier) | Yes, verified live and free | Lead-time projection input |
| Soil moisture (regional) | SMAP | NASA Earthdata / AppEEARS | ~9km | Yes (needs free login) | Dynamic soil state |
| Event-scale rainfall reconstruction | GPM IMERG | NASA GES DISC | ~0.1°, 30-min | Yes (needs free Earthdata login) | Historical validation |
| GSI susceptibility + event inventory | GSI Bhukosh/Bhusanket | Manual/portal-based, coverage-limited | GIS layer | Medium — only in ~21 mapped districts | Boosts confidence where available; not required |
| IoT (soil/rainfall) | Simulated (software-only) | MQTT publish, no hardware | Point/local | Yes (simulated) | Local correction demo |
| H3 grid | Computed by HydraSense | Local | Chosen resolution | Yes (compute) | Common spatial framework |

### 8.3 Practical acquisition tiers

- **Tier 1 — zero/low friction, scriptable, no approval wait:** DEM (OpenTopography), land cover (ESA WorldCover), forecast rainfall (Open-Meteo), geocoding (Nominatim). These form the backbone of the "live fetch attempted first" demo path from Section 7.3.
- **Tier 2 — free but needs a one-time registration (instant approval, no wait):** ERA5-Land (Copernicus CDS API key), GPM IMERG and SMAP (NASA Earthdata login), SoilGrids bulk access via Google Earth Engine (Google account + GEE signup). None of these gate on human review — the registration step is instant, but it is still a setup step to do ahead of time, not during a live demo.
- **Tier 3 — coverage-limited, not blocking:** GSI susceptibility maps and the ~91,000-event historical inventory. Available only in GSI's mapped districts (~21 as of 2025, verified in Section 4). The pipeline must not depend on this existing for a queried region — where it's absent, the system runs on the auto-derived physics+ML estimate with reduced confidence (Section 6, step 8), which is precisely the honest behavior the region-agnostic redesign is built around.

### 8.4 Historical event data for model training

The pooled XGBoost model needs real historical events to train on, and this remains the most genuinely hard data problem in the whole system — not because any recent event is hard to find, but because event-level completeness (exact date, time, coordinates) is uneven. Recent, thoroughly-documented disasters (e.g. the July 2024 Wayanad landslide, with public coordinates, dates, and post-event SAR-derived extent maps) are far more usable for event-centered temporal sampling than older or less-reported events. The model should be trained on whatever pooled real events are obtainable, from any region, rather than requiring balanced per-region representation — this is exactly what makes LORO (Leave-One-Region-Out) validation the meaningful test, rather than a per-region accuracy guarantee (Section 7.1).

### 8.5 Data fallback hierarchy

Every dynamic input has a defined degradation path, and the degradation is always visible in the output, never silent:

```text
Live local observation (IoT, where deployed)
        │ unavailable
        ▼
Live regional/satellite fetch (SMAP, GPM, ERA5-Land)
        │ unavailable
        ▼
Cached/pre-fetched bulk layer (SoilGrids WCS snapshot, prior DEM tile)
        │ unavailable
        ▼
Physics/terrain-only estimate, confidence flagged down
```

The backend propagates data-source status into every prediction object (see the API contract in the Technical Stack section, to be drafted). A prediction generated from a fallback layer must never render identically to one backed by a healthy live fetch — this is enforced at the UI level via the source/quality badges introduced in Section 6.

### 8.6 Known data availability risks

- **SoilGrids REST unavailability** (verified current, Section 7.3) — mitigated by bulk WCS/GEE pre-fetch, not a live per-query call.
- **Event inventory incompleteness** — an undated or imprecisely-located historical landslide cannot be used for strict event-time model training; this constrains dataset size more than it constrains geographic reach.
- **Spatial resolution mismatch** — regional soil/rainfall products (250m–11km) are coarser than the H3 output grid (H3 resolution 8: average hexagon area ~0.737 km², roughly 800–920m across depending on measurement axis — corrected here from an earlier "~0.46 km², 600–700m" figure that conflated H3's published edge-length value, 0.461 km, with its area; the two are different quantities); this is fused, not hidden, per principle 8.1.
- **Geotechnical parameter approximation** — SoilGrids-derived cohesion/friction-angle values rely on pedotransfer correlations built mainly on temperate soils; Indian laterite/residual hill soils are a known deviation case (Section 7.2). This is stated as a limitation, not silently absorbed into the uncertainty band without explanation.
- **GSI coverage limits** — real, currently ~21 districts; the system must degrade gracefully outside this footprint rather than assume it.

---

## 9. Physics Layer — Factor of Safety

### 9.1 The governing equation

HydraSense uses a simplified infinite-slope formulation:

$$FS = \frac{c' + (\gamma z\cos^2\beta-u)\tan\phi'}{\gamma z\sin\beta\cos\beta}$$

where $c'$ = effective cohesion, $\phi'$ = effective friction angle, $\gamma$ = soil unit weight, $z$ = soil depth, $\beta$ = slope angle, $u$ = pore-water pressure.

Pore pressure is derived from the dynamic soil-saturation ratio via the standard infinite-slope seepage-parallel-to-slope approximation:

$$u = m\,\gamma_w\,z\,\cos^2\beta$$

where $m$ is the saturation fraction and $\gamma_w$ is the unit weight of water. Both terms carry the same $\cos^2\beta$ exponent — an earlier working version used a single power of $\cos\beta$ for $u$, which was inconsistent with the $\cos^2\beta$ already present in the FS numerator's normal-stress component, since both derive from the same normal-stress decomposition. This has been corrected throughout.

**Interpretation:** FS > 1 is generally more stable; FS ≈ 1 is near limiting stability; FS < 1 is a theoretical failure condition. This is a model indicator, not a guarantee that a real landslide will occur — it is one input to the ML fusion layer (Section 10), not a standalone prediction.

### 9.2 Deriving geotechnical parameters automatically (replaces the manual lookup table)

Under the region-agnostic redesign (Section 6), $c'$, $\phi'$, and $\gamma$ are no longer drawn from a hand-curated per-region lookup table. They are derived from SoilGrids' bulk-fetched raster layers (Section 8.2/8.3) as follows:

- **Soil unit weight ($\gamma$)** — computed directly from SoilGrids' bulk-density layer. This is the most reliable of the three derivations, since bulk density is a direct SoilGrids output, not a correlation.
- **Effective friction angle ($\phi'$) and effective cohesion ($c'$)** — estimated from SoilGrids' texture fractions (clay/sand/silt) and organic-carbon content, via established geotechnical pedotransfer correlations that map soil texture class to typical strength-parameter ranges. This is the weaker of the derivations and carries the limitation already flagged in Section 7.2: these correlations were developed predominantly on temperate soils, and Indian hill terrain frequently has laterite or deeply weathered residual soils whose real strength behavior can diverge from the correlation's assumptions.
- **Soil depth ($z$)** — SoilGrids does not directly and reliably supply depth-to-bedrock everywhere; where a global soil-depth product is available for the query point, it is used, and where it is not, a conservative regional default is applied and explicitly flagged as a default, never presented as a measured value.
- Where local, literature-derived parameters do exist (e.g. published geotechnical studies for a specific well-studied event, such as the Wayanad Mundakkai–Chooralmala site), these are preferred over the auto-derived estimate for that specific location, and the system records which source was actually used per prediction — this is the same source/quality-badge principle from Section 6 and 8.5 applied at the parameter level, not just the layer level.

### 9.3 FS uncertainty — grounded in SoilGrids' own published intervals, not an arbitrary band

Rather than inventing a plausible-looking uncertainty range, HydraSense uses SoilGrids' own per-pixel prediction uncertainty (published as 5th/95th-percentile bounds around each soil-property estimate) to generate `FS_min` and `FS_max` alongside the central FS value:

```text
FS = 0.96
FS range = 0.82 – 1.11
```

This is more informative than a single FS value, and it is now a principled uncertainty source rather than an assumed one — the improvement enabled directly by the Section 6 redesign, since a manual lookup table would have required someone to invent a plausible range by hand.

Where no local historical calibration exists for a region (Section 6, step 8), the FS uncertainty band is deliberately widened beyond what SoilGrids' raw interval alone would suggest, to reflect the added uncertainty of applying a temperate-soil-calibrated correlation to unstudied terrain. This widening is the mechanical link between this section and the third factor of the confidence score (Section 11) — a never-seen region should visibly show a wider FS range, not just a lower final confidence number that hides where the uncertainty is coming from.

### 9.4 What this section deliberately does not claim

FS is an index for ML fusion, not a certified geotechnical slope-stability assessment. It should never be presented to an end user as a substitute for a site-specific geotechnical survey, and the final document's limitations section restates this explicitly (Section 18, to be drafted) rather than leaving it implied only here.

---

## 10. Machine Learning Fusion Layer

### 10.1 Role in the pipeline

The ML fusion layer is step 10 of the Autonomous Region Onboarding Pipeline (Section 6): it receives the physics-based Factor of Safety and its uncertainty band (Section 9), the static terrain/land-cover features and dynamic rainfall/soil-state features (Section 8), and the historical-context flag from step 8 (GSI-mapped or not) — and produces a single fused risk estimate per H3 cell. It does not replace the physics layer; it consumes FS as one input alongside terrain, land cover, and rainfall, so a physically meaningful stability signal is available to the model rather than raw covariates alone.

### 10.2 Recommended approach: XGBoost

XGBoost remains the recommended model, unchanged from the original architecture, because it:

- Trains quickly on the modest event counts realistically obtainable (Section 8.4)
- Handles heterogeneous tabular data without extensive preprocessing
- Captures nonlinear interactions between terrain, rainfall, and FS
- Works with relatively small, imbalanced datasets
- Provides feature importances (and, as a stretch goal, SHAP — the tech-stack decision belongs to Section 15, to be drafted)
- Supports probability-like outputs, which feed directly into the confidence score (Section 11)

### 10.3 Feature set — adapted for region-agnostic computability

Every feature must satisfy one constraint the original v5 feature list did not fully enforce: it must be computable for any queried location by construction, not dependent on a region having been manually curated. This changes two features from the original design:

| Feature | Status under the region-agnostic redesign |
|---|---|
| `lithology_class` | **Removed.** In v5 this fed a manual geotechnical lookup table (the old Section 6.11). That table no longer exists (Section 6, Section 9.2); cohesion, friction angle, and unit weight are now continuous SoilGrids-derived values passed to the physics layer directly, not a categorical key into a hand-built table. Feeding a now-nonexistent category into the model would silently reintroduce the manual-curation dependency the whole redesign removes. |
| `gsi_susceptibility_class` | **Retained, but redefined as optional-with-explicit-null.** For the ~21 GSI-mapped districts (Section 4, Section 8.3 Tier 3) this is populated and used. For every other location — the majority of hilly India this system targets — it is explicitly null, not defaulted to a "low susceptibility" class or silently imputed. XGBoost handles missing values natively via its default-direction split mechanism, which is what makes this workable: the model can learn "GSI class known vs. unknown" as informative in its own right, rather than the pipeline having to fake a value. |
| `historical_event_count_500m` | **Retained, same null-handling logic as above.** Populated where an event inventory exists for the region (GSI's ~91,000-event inventory, or other obtainable regional records — Section 8.4); null, not zero, where no inventory has been checked or exists. Encoding "no data" as 0 would train the model to treat data-sparse regions as demonstrably safe, which is precisely the false uniformity the honesty framing (Section 1, Section 7.1) exists to prevent. |

All other static features (`slope_deg`, `aspect`, `TWI`, `TRI`, `elevation`, `distance_to_stream_m`, `drainage_density`, `flow_accumulation`, `hand_m`, `curve_number`, `land_use_class`, `ndvi_mean`) and dynamic features (`rainfall_1h/3h/6h/24h`, `rainfall_72h_antecedent`, `rain_intensity_mm_hr`, `api_score`, `soil_saturation_ratio`, `factor_of_safety`, `factor_of_safety_min`, `factor_of_safety_max`, `simulated_ffgs_signal`, `simulated_gsi_signal`, `iot_anomaly_flag`) carry forward unchanged — every one of them is already derived from a globally-queryable source (DEM, land cover, SoilGrids, ERA5-Land/SMAP/Open-Meteo) rather than a per-region manual input, so none required adaptation for this redesign.

A new feature is added, sourced directly from the historical-context check already computed at pipeline step 8:

| Feature | Purpose |
|---|---|
| `has_local_calibration` | Boolean — did this region have GSI-mapped susceptibility or a usable local event inventory at prediction time? This is the single feature that lets the model itself learn a different effective decision boundary for calibrated vs. uncalibrated regions, and it is also read directly by the confidence score's third factor (Section 11) — the same underlying signal is used in two places for two different purposes, not computed twice. |

**Net feature count** — corrected against the actual v5 tables, not v5's own inline summary. v5's Section 11 implementation note states "14 static + 13 dynamic," but that figure is stale: the actual static-feature table (v5 Section 10) lists 15 rows, and the actual dynamic-feature table (v5 Section 11) lists 14 rows — 29 total in v5, not v5's claimed 27. Counting from the real tables: 15 static − 1 (`lithology_class` removed) = 14 static, 14 dynamic (unchanged), +1 (`has_local_calibration`) = **29 features** feeding the model. Whoever finalizes the technical-stack/schema section (Section 15) should use this corrected count, not v5's inline note, as the source of truth.

### 10.4 Training data strategy: pooled, not per-region

Per decision #1 (Section 6), the model is not trained on a fixed dual-pilot-region dataset. It is trained on the pooled union of whatever real, event-level-complete historical events are obtainable from any region — Himalayan, Western Ghats, Northeast, or elsewhere — with no requirement that regions be equally represented. This is a direct consequence of Section 8.4: event-level completeness (exact date, time, coordinates) is the actual bottleneck, not geographic reach, so the honest training strategy is to take every usable event wherever it exists rather than artificially balancing a dataset that would need to be invented to look balanced.

This has a direct implication that the document states plainly rather than leaves implicit: the trained model's effective skill is not uniform across regions, because its training data is not uniform across regions. A region well-represented in the pooled event set (e.g. Western Ghats, given denser recent documentation such as the July 2024 Wayanad landslide) will be better-fit than a region contributing few or no training events. This is the same honesty principle from Section 1 and Section 7.1 restated at the model-training level, and it is exactly why Section 10.6 below treats LORO, not a single pooled train/test split, as the load-bearing validation evidence.

### 10.5 Event-centered temporal sampling

Rather than one training row per event, each event contributes a short sequence of samples at multiple lead times before the event:

```text
Event E
│
├── T - 72h
├── T - 48h
├── T - 24h
├── T - 12h
└── T - 6h
```

This gives the model information about how an event's precursor signals (rainfall accumulation, soil saturation, FS) evolve in the run-up to failure, rather than only a single snapshot. These are additional training samples, not additional independent events — a rule that matters more under the pooled-training strategy above than it did under the original pilot-region design, because pooling across regions makes it easier to lose track of which samples share an underlying event. Leave-One-Event-Out and Leave-One-Region-Out validation (Section 10.6, detailed in Section 17) must both hold out every timestep of an event together, and LORO must hold out every event belonging to a region together — a held-out region with only its T-6h sample removed while its T-72h sample remains in training would leak information across the boundary the test is meant to establish.

### 10.6 Why Leave-One-Region-Out is the central evidence, not a supplementary check

Leave-One-Event-Out validation (train on all events except one, test on the held-out event) proves the model generalizes across events — but if every event in the pooled dataset comes from a small number of well-documented regions, LOEO alone would only demonstrate that HydraSense works well near the regions it happened to have training data for. That is precisely the claim decision #2 (Section 6, Section 7.1) says this project must not make.

Leave-One-Region-Out (LORO) is the test that actually speaks to the region-agnostic claim:

```text
Training:
All events from all regions except Region R

Validation:
All events from Region R — held out entirely, every event and
every timestep, including from feature-derived pooled statistics
```

The prediction run for Region R uses only R's own auto-derived terrain, land cover, and SoilGrids-derived geotechnical parameters (Section 6, Section 9.2) — nothing about R is available to the model except what the Autonomous Region Onboarding Pipeline would compute for a genuinely new location. This is what makes LORO's result a fair proxy for "how would HydraSense perform on a hilly region it has never seen," which is the actual product claim, rather than "how does it perform on a held-out slice of regions it was implicitly tuned toward."

The full LORO methodology, metrics, and reporting format (including the hazard-type split and spatial block validation) belong in Section 17 (Validation Strategy), to be drafted later in this document. What matters at the model-design stage, stated here so it is not lost by the time Section 17 is written: LORO results, not overall pooled accuracy, are the number that should appear first whenever this project's region-agnostic claim is defended to a judge. A high pooled accuracy driven by a handful of data-rich regions would be a misleading headline figure precisely because of the training asymmetry described in Section 10.4.

### 10.7 Outputs

```text
risk_score        = 0–100 (Section 11 tiers this into Green/Yellow/Orange/Red)
predicted_tier     (project-defined cut points, Section 11)
class_probability  (P_class — feeds the model-confidence factor of Section 11's
                     three-factor confidence score)
feature_contributions (feature_importances_ by default; SHAP if the stretch
                     goal is reached)
```

`class_probability` is explicitly not presented as a calibrated probability of a real event occurring — the same honesty distinction v5 already established for the confidence score (carried into this document's Section 11) applies here at the model-output level: it is the trained classifier's own confidence in its prediction, not a statistically calibrated likelihood, and the two should not be conflated when the number is shown to a judge or end user.

### 10.8 Alternatives considered

- **Random Forest** — kept as a baseline comparison, not the primary model; useful for sanity-checking XGBoost's feature importances against a structurally different ensemble method.
- **PSO-BP** — usable only if a working implementation already exists from prior project work; its published accuracy figures must not be compared directly against this project's LOEO/LORO results unless the datasets and validation methodology are actually comparable, which they are not by default.
- **LSTM/GRU** — a plausible future upgrade once event history is large enough to support a genuine temporal sequence model, not the event-centered snapshot sampling of Section 10.5. Not adopted as the core model now — the pooled event count (Section 10.4) is not yet large enough to justify it, and introducing it prematurely would risk overfitting on a training strategy already stretched thin by pooling across regions.

### 10.9 What this section deliberately does not claim

The ML fusion layer is a fusion and calibration mechanism over an already physically-grounded FS signal (Section 9), not an independent black-box predictor asked to learn slope stability from scratch. Its skill is bounded by both the physics layer's own known limitations (Section 9.4, Section 7.2) and the training-data asymmetry stated in Section 10.4 — and per Section 10.6, its region-agnostic claim is only as strong as its LORO performance, which this document is committed to reporting honestly in Section 17, including if that performance turns out to be weaker in under-represented regions than in well-documented ones.

---

## 11. Decision Engine — Risk, Confidence, Lead Time

### 11.1 Role in the pipeline

The decision engine is the final translation step: it takes the ML fusion layer's raw outputs (Section 10.7 — `risk_score`, `class_probability`, `has_local_calibration`) together with the physics layer's FS uncertainty band (Section 9.3) and forecast rainfall (Section 8), and turns them into the four things an end user or judge actually reads: a risk tier, a confidence number, a lead time, and a named threat product. Nothing in this section runs a new model — it packages and interprets outputs already computed upstream.

### 11.2 Risk score and tiering

The pooled model's `risk_score` (0–100) is tiered using project-defined cut points, unchanged from the original architecture:

```text
Green   = 0–29
Yellow  = 30–54
Orange  = 55–74
Red     = 75–100
```

| Tier | Interpretation |
|---|---|
| Green | Low modeled risk |
| Yellow | Elevated / monitor |
| Orange | Significant risk / prepare |
| Red | High modeled risk / trigger alert workflow (Section 12, to be drafted) |

These are project decision thresholds, not official government warning thresholds, and must not be presented as such unless separately validated and adopted by an authorizing agency.

**Calibration linkage — required before finalizing.** These are currently round-number defaults, not derived from the model's actual behavior. Once LORO's reliability diagram (Section 17, to be drafted) is available, these cut points should be revisited against where predicted probabilities actually separate true from false positives — and, given the training asymmetry established in Section 10.4, this check should be run per data-availability tier (calibrated vs. uncalibrated regions), not once globally. A single global reliability curve would average over exactly the asymmetry Section 10.4 says must not be hidden; if the model is systematically over- or under-confident specifically in uncalibrated regions, that is the more important place to catch it, not a detail to lose inside an aggregate curve.

### 11.3 Confidence score — three factors, not two

The original architecture's confidence score combined two uncertainty sources. Per the region-agnostic redesign, a third is now required — regional historical-calibration availability — because a system that claims to run anywhere must say, per region, how much that claim is actually backed by local evidence (Section 2's objective; Section 7.1).

$$Confidence = 100 \times P_{class} \times (1 - FS_{band\ penalty}) \times C_{cal}$$

| Term | Source | What it captures |
|---|---|---|
| $P_{class}$ | `class_probability` (Section 10.7) | The trained classifier's own confidence in its prediction — aleatoric, statistical |
| $FS_{band\ penalty}$ | FS uncertainty band (Section 9.3) | Geotechnical-parameter-range uncertainty — epistemic, physics-side. Already deliberately widened by Section 9.3 for regions with no local historical calibration |
| $C_{cal}$ | `has_local_calibration` (Section 10.3) | New. 1.0 if the region has GSI-mapped susceptibility or a usable local event inventory; a fixed discount constant ($k < 1$) otherwise |

**Why $C_{cal}$ is not double-counting what the widened FS band already does.** Section 9.3's widened band and this new $C_{cal}$ term both trace back to the same root cause — no local calibration data — but they penalize two genuinely different things. The widened FS band reflects uncertainty in a physical parameter estimate (does the pedotransfer correlation's cohesion/friction-angle output actually hold for this soil). $C_{cal}$ reflects uncertainty in the trained model's own experience (has the pooled XGBoost model, per Section 10.4's training-data asymmetry, ever seen an event from a region like this one at all). A region could in principle have a well-behaved, narrow FS band (ordinary soil, no surprising pedotransfer mismatch) and still have zero training-event representation — those are independent failure modes, and the confidence score should not collapse them into one term just because both happen to correlate with "no GSI history."

**Illustrative example — same terrain, two calibration states.** ($k = 0.75$) here is a placeholder, exactly like the original FS-band-penalty was in the prior architecture; the real value should be derived empirically from LORO's confidence-vs-accuracy relationship (Section 17) before final evaluation, not fixed by inspection.

```text
Calibrated region (GSI-mapped, has_local_calibration = true):
  Risk = 82, P_class = 0.91, FS_band_penalty = 0.14 (moderate), C_cal = 1.0
  Confidence = 100 × 0.91 × 0.86 × 1.0 = 78

Uncalibrated region (has_local_calibration = false), same P_class:
  Risk = 82, P_class = 0.91, FS_band_penalty = 0.22 (widened per 9.3), C_cal = 0.75
  Confidence = 100 × 0.91 × 0.78 × 0.75 ≈ 53
```

The model was equally confident in its own output both times ($P_{class} = 0.91$) — the displayed confidence still drops by 25 points because the other two terms are honest about what the model and the physics layer don't actually know about that region. This is the demo-visible behavior decision #2 (Section 1, Section 7.1) is built around: identical risk score, visibly different confidence, for a principled reason a judge can be shown, not a cosmetic difference.

**Honest characterization** — this remains an engineered index, not a calibrated probability. All three terms are different kinds of uncertainty (one aleatoric, two epistemic) multiplied together because it is a practical way to surface all three in one number, not because there is a formal derivation showing they combine multiplicatively into a meaningful joint probability. This must be stated explicitly wherever the confidence score is shown to a judge or end user: claim "a combined uncertainty index that separately reflects model confidence, physical-parameter uncertainty, and local-data availability," never "a calibrated probability of correctness."

### 11.4 Algorithmic lead-time estimation

Unchanged in method from the original architecture — no hardcoded demo value (e.g. a fixed "35 min"):

```text
Current state
      ↓
Forecast rainfall (Open-Meteo, Section 8.3 — Tier 1, always attempted live first)
      ↓
Project future dynamic features
      ↓
Run trained model at each forecast horizon
      ↓
Find first projected RED crossing
      ↓
lead_time_min
```

1. Obtain forecast rainfall for the queried location.
2. Project rainfall accumulation/intensity forward.
3. Recompute rainfall windows, API score, projected soil saturation, and FS at each horizon.
4. Run the trained model at each supported forecast horizon.
5. Find the earliest horizon where the projected tier reaches Red.
6. Report the time difference as `lead_time_min`.
7. If no Red crossing occurs within the forecast window, report "No RED crossing in forecast window" — never a fabricated number.
8. Do not invent minute-level precision from an hourly forecast source; where interpolation is used between hourly points, it must be labeled as interpolation, not presented as native forecast resolution.

**Region-agnostic note:** this loop requires nothing specific to the queried region beyond what the Autonomous Region Onboarding Pipeline (Section 6) already resolves — it works identically for a GSI-mapped district and a never-seen location, because Open-Meteo forecast rainfall (Section 8.3, Tier 1) is globally live. What differs between the two is not whether a lead time can be computed, but how much confidence (Section 11.3) should accompany it: a lead-time-to-Red figure for an uncalibrated region carries the same reduced-confidence caveat as the present-moment risk score, and the dashboard (Section 13, to be drafted) must surface that alongside the lead-time number itself, not only on the current-moment tile.

### 11.5 Threat products — Risk, Imminent Threat, Persistent Threat

Rather than presenting Risk, Confidence, and Lead Time as unrelated dashboard numbers, they are packaged into three named products deliberately aligned with vocabulary already operational in India's own upstream guidance system. Verified for this section: IMD, in partnership with WMO and the US Hydrologic Research Center, operationalized SAsiaFFGS in October 2020; it produces Flash Flood Risk (FFR) at 24-hour validity and Imminent/Persistent Flash Flood Threat (IFFT/PFFT) at shorter (approximately 6-hour) validity for nowcasting. (SAsiaFFGS documentation also defines a third, related product — Forecasted Flash Flood Threat, FFFT — which this document does not attempt to mirror; the three-product structure below corresponds specifically to FFR/IFFT/PFFT.) This confirms and slightly sharpens the FFR/IFFT/PFFT framing already used for SAsiaFFGS in Section 4's comparison table — note this is introduced here, not "already named" in Section 4's condensed table, which lists SAsiaFFGS's grid size and lead time but not its named output products.

Matching this structure is not cosmetic: disaster-management users and IMD-trained forecasters already read hazard information in this three-horizon shape, so aligning with it reduces the interpretation burden on the person using the dashboard, and gives the project a direct, citable point of alignment with the national system it downscales (Section 4).

| Product | Time horizon | Computed from | Status |
|---|---|---|---|
| Risk | Present-moment, 24h validity | Section 11.2's tiered 0–100 score | Already built |
| Imminent Threat | Hours-ahead | Section 11.4's forecast-horizon loop — first projected Red crossing | Already built, relabel only |
| Persistent Threat | Sustained/trend | New — see below | New, lightweight |

**Persistent Threat — method:**

```text
For the last N observed forecast horizons (e.g. last 3):
    Is the tier Red or Orange in every one?
    Is soil_saturation_ratio / api_score trending upward?
        ↓
If both true → Persistent Threat = ELEVATED
Else          → Persistent Threat = NOT SUSTAINED
```

This reuses state already computed in Section 11.4's forecast loop (the tier at each horizon, and the underlying `soil_saturation_ratio`/`api_score` values) — it requires no new model and no new data source. It answers a different question from Risk and Imminent Threat: not "how bad is it right now" or "when might it cross Red," but "has the danger been building for a while, or is this a single spike likely to pass."

**Honest scope note:** unlike SAsiaFFGS's FFR/IFFT/PFFT, which are independently derived hydrometeorological indices with their own operational validation history, this project's three products are repackagings of the same underlying ML fusion output (Section 10) at different time slices, run through the same confidence machinery (Section 11.3). This should be stated plainly if a judge asks, rather than implying independent derivation from separate models.

### 11.6 What this section deliberately does not claim

The decision engine does not claim its 0–100 risk score or its tier boundaries are calibrated against real-world outcome frequencies until LORO validation (Section 17) says so — Section 11.2's cut points are stated as defaults pending that check, not as evidence-backed thresholds. It does not claim the confidence score is a statistically rigorous joint probability (Section 11.3). And it does not claim lead time is precise below the temporal resolution of the underlying forecast product (Section 11.4). Each of these is a deliberate scope limit restated here, not an oversight to be discovered later in the document's limitations section (Section 18, to be drafted).

---

## 12. Alert Architecture

### 12.1 Role in the pipeline

Alert Architecture consumes the decision engine's output (Section 11) — risk tier, confidence, lead time, and the three named threat products (Section 11.5) — and converts a tier crossing into a standardized, dispatchable alert object. Nothing in this section computes risk; it packages and disseminates a decision already made upstream, exactly as Section 11 packages the ML fusion layer's raw output rather than re-scoring anything itself.

### 12.2 Baseline pipeline: CAP 1.2

Unchanged in structure from the original architecture:

```text
Risk tier reaches Orange/Red (Section 11.2)
          ↓
Alert service
          ↓
CAP 1.2 XML
          ↓
SACHET-compatible webhook
          ↓
SMS / Cell-Broadcast simulation
          ↓
Dashboard alert feed
```

Conceptual field structure (CAP 1.2's own defined schema — identifier, status, msgType, scope, and an info block carrying category, event, urgency, severity, certainty, headline, description, and an area block with areaDesc and polygon) is populated as follows for a HydraSense-triggered alert:

| CAP field | Populated from |
|---|---|
| `identifier` | `HYDRASENSE-{region_code}-{sequence}` — `region_code` is read off Section 6 step 1's boundary-resolution call (e.g. an administrative or geocode slug for the resolved location), not a hand-picked abbreviation set per pilot region the way the original architecture's own example (`HYDRASENSE-WYD-000123`, for Wayanad) implied |
| `status` | Actual (or Exercise for the demo shortlist, Section 7.3) |
| `msgType` | Alert / Update / Cancel — see 12.4 |
| `event` | Flash Flood / Landslide Risk |
| `urgency`, `severity`, `certainty` | Derived from the triggering threat product (12.5), not fixed |
| `headline`, `description` | Auto-generated from risk tier, confidence, and lead time (12.3) |
| `area` | The triggering H3 hex or merged hex-union polygon (12.4) |

### 12.3 Carrying the three-factor confidence into the alert payload

Section 11.3 established that HydraSense's confidence score is a three-factor honesty index (model probability, FS-uncertainty width, regional historical-calibration availability), and Section 1's load-bearing claim is that this must be visible, not just computed. A CAP alert that reports only tier and severity — with confidence living solely in the dashboard UI — would let that honesty framing evaporate the moment the alert leaves HydraSense's own interface (e.g. consumed by a third-party CAP feed or SACHET's RSS output, Section 4.6). CAP 1.2 permits arbitrary `<parameter>` key/value extensions inside `info`; HydraSense uses this mechanism rather than inventing a non-standard schema:

```xml
<parameter><valueName>confidence_score</valueName><value>53</value></parameter>
<parameter><valueName>has_local_calibration</valueName><value>false</value></parameter>
<parameter><valueName>lead_time_min</valueName><value>No RED crossing in forecast window</value></parameter>
<parameter><valueName>data_source_quality</valueName><value>terrain: live; soil: cached; rainfall: live</value></parameter>
```

The auto-generated description text also states the calibration status in plain language whenever `has_local_calibration = false` — e.g. noting that the region has no local historical event record and that the estimate is physics-derived with reduced confidence — because a human reading only the rendered alert text (not inspecting CAP parameters) must still receive the honesty signal Section 11.3 requires. This is the same principle as Section 6's source/quality badges, applied at the alert-object level rather than the dashboard-tile level.

### 12.4 Alert lifecycle

Unchanged from the original architecture:

```text
New Orange/Red tier      → CAP msgType=Alert, new identifier
Same tier next cycle     → suppressed (cooldown window), dashboard updates silently
Tier changes             → CAP msgType=Update, same identifier
Drops to Green/Yellow    → CAP msgType=Cancel, same identifier
Adjacent hexes co-trigger → merged into one alert (polygon union), not N separate alerts
```

A cold-start guard prevents the very first scoring cycle after a new region is onboarded (Section 6) from firing spurious alerts if hexes happen to start at Orange/Red — the pipeline must complete at least one full cycle before any `msgType=Alert` is issued for a newly resolved region.

**Two-person authorization gate.** A model-generated `msgType=Alert` is held in a pending state until two designated human roles for the alert's jurisdiction (a duty officer and the district-level authority or delegate) each confirm it before dispatch to SACHET/Cell Broadcast (12.6) proceeds. This is stated here, as a backend/alert-layer requirement, rather than left as something only the dashboard happens to render (Section 13) — the authorization model must be defined once, in the layer that actually gates dispatch, with the dashboard's [AUTH] indicator (Section 13) merely displaying a state that already exists here, not inventing one. This directly reflects the "decision-support, not autonomous alerting" framing established in Section 3 (What HydraSense Is — and Is Not): the pipeline recommends and drafts the CAP object; it does not unilaterally publish it.

### 12.5 Three threat products, three distinct alert behaviors

Section 11.5 packaged Risk, Imminent Threat, and Persistent Threat as three named products sharing one underlying model. They do not, however, warrant identical alert behavior — treating all three as equivalent triggers for the same `msgType=Alert` would both misrepresent their different time horizons and risk exactly the kind of alert fatigue Section 12.4's cooldown logic already guards against.

| Threat product | Trigger condition | CAP mapping | Rationale |
|---|---|---|---|
| Risk | Present-moment tier reaches Orange/Red (Section 11.2) | `msgType=Alert`, `urgency=Immediate` | The core, present-tense hazard alert |
| Imminent Threat | Forecast loop (Section 11.4) projects a Red crossing at a future horizon, before Risk itself has reached Red | `msgType=Alert`, `urgency=Expected`, distinct identifier, description states the projected lead time | This is where HydraSense's actual lead-time differentiator (Section 5, item 5) becomes visible as an alert a judge or duty officer receives before the present-moment tier turns Red — the entire point of computing it |
| Persistent Threat | Tier has stayed Red/Orange with rising `soil_saturation_ratio`/`api_score` over the last N cycles (Section 11.5) | Not a new alert — appended as a `<parameter>` on the already-active Risk alert, via `msgType=Update` | Persistent Threat's own definition is backward-looking (has the present-moment tier stayed Red/Orange over recent cycles), which means the Risk alert is necessarily already open whenever this condition can be true — there is no scenario where Persistent Threat fires while only an Imminent Threat alert is open. Firing a third independent alert would also create a redundant identifier for the same underlying event and directly contradict the anti-fatigue intent of 12.4 |

### 12.6 SACHET/CAP dissemination — verified update

Section 4.6's original constraint stands unchanged: SACHET accepts feeds only from recognized government agencies (IMD, CWC, INCOIS, DGRE, FSI, and State Disaster Management Authorities), so a third-party pilot system cannot self-publish live alerts into it without sponsorship from GSI, CWC, a State SDMA, or NDMA. HydraSense's CAP output remains a technical-readiness demonstration under Section 4.6/7.3, not a live integration claim.

One relevant development has occurred since the original comparison in Section 4: NDMA, in coordination with the Department of Telecommunications, nationally rolled out Cell Broadcast as a SACHET dissemination channel alongside SMS, tested in May 2026 and now operating across all states and union territories. Cell Broadcast delivers near-simultaneously to every device in a targeted area without requiring individual number registration — a meaningfully better fit for a short-fuse flash-flood/landslide alert than SMS fan-out, which is the channel the original architecture's SMS-simulation language implicitly assumed as primary. This does not change anything HydraSense needs to build: CAP 1.2 output is channel-agnostic by design, so the same alert object that would have gone out via SMS now has a faster, better-targeted path available once sponsorship exists. It does slightly strengthen the technical-readiness argument in Section 4/7 — the downstream channel this project is positioning itself to eventually feed has itself gotten faster and more automatic since the original architecture was written, which is worth stating to a judge as evidence the CAP-compliance framing is aimed at where the ecosystem is actually heading, not where it used to be.

### 12.7 Offline-first layered extension (optional)

*(As in the original architecture, this is a proposed additional layer, not a replacement — 12.2–12.6 remain the complete, sufficient digital-dissemination baseline. This subsection documents what is gained by adding it, gated on team bandwidth.)*

**Rationale.** The CAP pipeline above depends on continuous internet connectivity between the risk-tier decision and the citizen-facing alert. In flash-flood/landslide scenarios specifically, the triggering rainfall event is also the event most likely to disrupt cellular data and grid power — the same structural concern already noted for the demo itself in Section 7.3, here applied to the alert's last mile rather than to HydraSense's own live data fetches.

```text
Layer 0 — Edge Autonomous Trigger: local sensor node (rain gauge/soil
  moisture/tilt) + on-device threshold rule → local hooter/blinker
  directly. Solar + battery backed. Zero dependency on layers above.

Layer 1 — Local Relay (point-to-multipoint, not mesh): sensor node(s)
  → LoRa → gateway (ESP32 + GSM module) → SMS to a registered
  caretaker contact. Runs on GSM voice/SMS coverage, which in hilly
  terrain typically outlasts 4G data.

Layer 2 — Regional Cloud Fusion (= Sections 6–11, unchanged)

Layer 3 — Digital Dissemination (= 12.2–12.6, unchanged)

Layer 4 — Human Relay Backstop: per-village nodal contact record;
  receives the alert via whichever of Layers 1/3 is reachable;
  performs the physical notification step manual systems rely on.
```

| Connectivity state | What still fires | What's lost |
|---|---|---|
| Full connectivity | All layers — full risk score, CAP/CB, dashboard | Nothing |
| Internet down, GSM up | Layer 0 (siren) + Layer 1 (SMS via gateway) + Layer 4 | Regional risk score, confidence, lead time, dashboard |
| Total blackout | Layer 0 only (solar/battery) | Everything except immediate local alarm |
| Cloud/backend outage | Layers 0, 1, 4 unaffected | Same as internet-down case |

A second, alert-specific instance of the honesty principle. `instrumented_hexes` (which hexes actually carry a Layer 0/1 node, real or simulated-and-labeled-as-such) is, like `has_local_calibration` in Section 11.3, necessarily empty for most of any newly onboarded region — Layer 0 requires physical siting, which the Autonomous Region Onboarding Pipeline (Section 6) cannot conjure for a location it has just resolved. A region can therefore be simultaneously well-calibrated in the confidence sense (GSI-mapped, historical events available) and have zero alert-resilience redundancy in the connectivity sense, or vice versa — these are independent gaps, and the dashboard (Section 13.4) must show which uninstrumented-hex fallback state (Layer 3-only) a given hex is actually in, the same way it shows `has_local_calibration`, rather than implying every alert has the same resilience floor.

**Feasibility (SIH team-scale constraint).** 1–2 real physical Layer 0 nodes (ESP32 + rain gauge + soil sensor + tilt + hooter + solar/battery, roughly ₹1,500–2,500 per node) with the remainder of `instrumented_hexes` simulated in software and labeled as such, consistent with the existing simulated-IoT convention (Section 8.2); Layer 1 as point-to-multipoint only — multi-hop mesh routing is explicitly out of scope, a distinct RF-networking problem outside a hackathon build; Layer 4 is a database field and message template at negligible cost. If the team lacks embedded/RF experience, Layers 0–1 can remain fully simulated (labeled as such, per the same source/quality-badge convention used throughout) without weakening 12.2–12.6.

**Honesty statement, if adopted.** Layer 0's on-device threshold rule is simpler and less accurate than the Section 10 fusion model — it trades predictive accuracy for guaranteed availability during exactly the connectivity failure the fusion model cannot help with. This trade-off must be stated wherever Layer 0 is described, consistent with the same standard already applied to FS-as-index (Section 9.4) and confidence-as-engineered-index (Section 11.3).

### 12.8 What this section deliberately does not claim

This section does not claim HydraSense has, or is close to obtaining, real publishing rights into SACHET or the new Cell Broadcast channel — both remain gated on institutional sponsorship exactly as Section 4.6 states, and 12.6's update describes a channel getting more capable, not a door opening for a third party. It does not claim Layer 0/1 hardware (12.7) is deployed at any meaningful scale — at most a couple of physical nodes, with the rest explicitly simulated and labeled. And it does not claim the three threat products (12.5) are independently validated alerting channels; per Section 11.5's own honest-scope note, they remain repackagings of one underlying model output at different time slices, and an alert generated from any of them inherits that model's Section 10.9 and 11.6 limitations, not a separate, stronger evidentiary basis of its own.

---

## 13. Dashboard & UI/UX

### 13.1 What the dashboard must answer

Unchanged from the original architecture — five questions, immediately:

1. Where is the risk?
2. How severe is it?
3. Why is it high?
4. How confident is the prediction?
5. How much forecast lead time is available?

Packaged as the three named threat products (Section 11.5) rather than four flat, unrelated numbers:

```text
RISK (24h)            82    TIER: RED
IMMINENT THREAT        RED in 51 min
PERSISTENT THREAT       ELEVATED (3/3 windows)
CONFIDENCE             53
```

Under the region-agnostic redesign this same panel now has to be honest about why confidence sits where it does, not just report the number — a judge or duty officer reading `CONFIDENCE 53` beside `RISK 82` for the first time should not have to guess whether that gap means the model is unreliable in general. Section 13.4 below is the direct answer to that.

### 13.2 Roles & access — unchanged in structure, resolved dynamically per region

Exactly two built interfaces, gated by role, not by screen size:

| Role | Who | Primary job |
|---|---|---|
| Decision Authority | District/state disaster-management duty officers for the queried region's jurisdiction | See full risk picture, authorize dispatch (Section 12's two-person gate), own the Incident Action Plan |
| Response Unit | Field-team coordinators and leads | Receive assigned tasks, navigate to site, report status — consumes decisions, doesn't issue them |

No third citizen-facing surface is built as a standalone product — the citizen-facing outcome is delivered through SACHET/Cell Broadcast (Section 12.6), not an app HydraSense owns. This is unchanged from the original design, and it remains consistent with Section 4.6's institutional constraint: a citizen-preview panel exists only as a small illustrative element inside the Decision Authority console (13.3), never a demoed standalone citizen product.

**What genuinely changes under the region-agnostic redesign:** the original design hardcoded a specific chain-of-command breadcrumb for one pilot region. That is exactly the kind of manual per-region curation decision #1 (Section 6) eliminated from the data pipeline, and leaving it hardcoded in the UI would quietly reintroduce it at the interface layer. The chain-of-command breadcrumb — [National authority] → [State authority] → [District authority] → [Deployed unit] — must instead be resolved from the same boundary-resolution step that already runs for any queried location (Section 6, step 1): India's own administrative-hierarchy data (state and district containing the resolved boundary) is a globally-queryable, structured lookup, exactly the kind of source Section 6's pipeline already depends on, so naming the actual jurisdiction for a newly queried region requires no new manual step — it is a second field read off the same boundary-resolution call, not a second onboarding process.

### 13.3 Design philosophy, color, and typography — unchanged, not region-dependent

The interface is a command instrument, not a SaaS dashboard — built for a duty officer making an authorized decision quickly under degraded conditions, closer in spirit to an aircraft instrument panel than a startup product. This design intent, and the concrete system built from it, do not depend on which region is queried, so they carry forward from the original architecture without adaptation:

- **Color:** quiet, layered near-black surfaces everywhere except the four risk tiers (Green/Yellow/Orange/Red), the only saturated color permitted, always paired with a word label, never color alone — checked against a color-blindness simulator before finalizing rather than assumed distinguishable. A single muted terrain-teal accent for brand and active states; no gradients except the literal risk-scale legend, because that gradient is data.
- **Typography:** one family, two weights — IBM Plex Mono for every number, coordinate, and timestamp; IBM Plex Sans for every label and sentence. No ALL-CAPS labels.

**One necessary correction versus the original design.** The original spec tied the citizen-preview panel's local-script font pairing to the old, now-removed Region Configuration Layer (the same manual per-region YAML decision #1 eliminated — Section 6). Under the region-agnostic redesign there is no region-config value left to hang this on. The fix is the same pattern as 13.2's chain-of-command breadcrumb: the local script (e.g. a Devanagari- or Dravidian-script Noto Sans variant) is resolved from the region's administrative-hierarchy lookup (state/district → official regional language), the same call that resolves the chain-of-command breadcrumb, not a value someone enters per region. This is a small but real instance of the same discipline Section 10.3's feature-count correction applied to the ML feature tables: a leftover dependency on the old manual-config design has to be found and re-derived from Section 6's actual pipeline, not left quietly assuming a mechanism that no longer exists.

### 13.4 Decision Authority console — main build

Three fixed horizontal zones, identical placement across every screen.

**Header.** Brand mark (an original hexagon, echoing the H3 grid) · the dynamically-resolved chain-of-command breadcrumb (13.2) · live clock and situation-status pill · the two-person [AUTH] indicator, displaying the authorization state Section 12.4's alert lifecycle actually gates dispatch on (not inventing a separate one) · a role switcher · a quiet ? legend covering tiers, threat products, and log-entry types · a greyed "National View — Phase 2" tab, deliberately not built this phase.

**Left column — institutional record.** Force/readiness status; an append-only, timestamped message-form feed; a tier-colored alert-activation record; an audit-hash strip for tamper-evidence; routine data refreshes stay silent while a genuine new alert gets one brief pulse and a colored log entry — the interface-level counterpart of Section 12.4's cooldown/suppression logic, so the UI does not re-introduce the alert fatigue the backend already guards against.

**Center — the map.** Literal H3 hexagons, not a photorealistic basemap, signaling a computed grid rather than false photographic precision. A three-way hazard toggle — Compound / Flood / Landslide — where Compound mode renders the higher of a hex's two tiers as its color (never a blended average, which would understate the more severe hazard), with a small dual-tier edge indicator when the two differ, keeping Compound mode consistent with the requirement that flood and landslide metrics are never silently collapsed into one figure (a requirement that traces back to Section 17's hazard-type split, to be detailed there). A time-scrubber (-72h to the forecast window) rewinds hex coloring when dragged, with any tier crossing marked on the timeline itself. Lower-confidence hexes render at slightly reduced saturation within their tier — subtle at a glance, informative on a careful look.

**Region-agnostic addition, not present in the original design:** a hex's reduced saturation under the rule above must now visibly trace back to which of the three confidence factors (Section 11.3) is driving it — a wide FS band (geotechnical uncertainty) and a low `has_local_calibration` factor look identical as a bare desaturation effect, but they mean different things to a duty officer deciding how much to trust the number. Hovering or tapping a desaturated hex surfaces a one-line reason (e.g. "no local historical calibration" or "widened geotechnical uncertainty") rather than leaving the officer to infer the cause from a single visual cue. This is the map-level expression of the same principle Section 12.3 applies to the alert payload: confidence must travel with a reason, not just a number.

A second, independent hex-level indicator: alert-resilience floor, not prediction confidence. Section 12.7 establishes that `instrumented_hexes` (real or simulated-and-labeled Layer 0/1 nodes) is a separate axis from `has_local_calibration` — a hex can be well-calibrated but have no offline-alert redundancy, or vice versa. The map therefore carries a second, distinct hex marker (a small filled/hollow dot at the hex's corner, independent of the tier-color fill and the confidence-desaturation effect) showing whether that hex falls back to Layer 3 (digital-only) or has Layer 0/1 coverage if connectivity drops. Collapsing this into the same desaturation cue used for confidence would conflate two genuinely different questions — "how much do we trust this risk number" and "will an alert still reach this hex if the internet goes down" — the same anti-conflation discipline Section 11.3 already applies to keep the FS-band-penalty and C_cal factors from being treated as one thing just because both trace back to "no local data."

**Right column — the explainability stack**, mirroring the actual pipeline (Section 6): hydrometeorological telemetry as an inline sparkline; FS shown as a large central value with its uncertainty range as a bracket, never a false-precision point figure, and — new under this redesign — a visible tag when that range has been widened for lack of local calibration (Section 9.3), so the widening itself is not hidden inside a wider-looking-but-unexplained bracket; feature-contribution bars (`feature_importances_` by default, SHAP as the stretch goal — Section 10.2), collinear-group features labeled at the group level rather than implying one feature alone carries the weight; an editable Incident Action Plan with a dashed "live document" border.

**Validation and data-source-health panel, added here to close a gap this section originally left unspecified.** Sections 16.8 and 17.9 (drafted later in this document) both assume a dashboard element surfacing frozen LOEO/LORO results and per-layer data-source health — this paragraph is that element, specified in Section 13 rather than left as a forward reference to a panel that was never actually placed. A collapsible strip beneath the explainability stack shows: the combined and per-hazard-type LOEO/LORO figures frozen at Section 16.6's Stage 4 gate (never live-recomputed on the dashboard itself — recomputing validation metrics per page load would silently reintroduce the "iterate until it looks better" risk Section 17.9 exists to prevent), the confidence-factor check from Section 17.8 (has the currently-viewed region's confidence been checked against LORO's calibrated/uncalibrated comparison), and a compact per-layer status list (live/cached/fallback) mirroring the footer's agency-connection dots but scoped to data freshness rather than agency identity. This panel is read-only and dated (\"validation frozen: <date>\"), never implying same-session recomputation.

**Footer.** A strip of agency-connection dots (upstream data sources and services this region's pipeline is actually using — which sources light up depends on which layers Section 6's onboarding pipeline resolved live versus cached for this specific region, not a fixed list) — quiet when healthy, drawing the eye only on fault. This makes the multi-source-fusion claim (Section 5, item 2) literal and continuously visible, and doubles as the region-level rendering of the source/quality badge system Section 6 (step 11) and Section 7.3 already require.

**States.** Loading: a thin animated hairline, never a spinner. No data yet: dashes in place of values, preserving layout. Fallback/stale: the panel border shifts to caution yellow with a "cached · Xm ago" tag — the direct visual form of Section 7.3's fallback-is-shown-not-hidden principle, applied consistently to every panel, not only a dedicated data-health panel.

**Print/briefing export.** A dedicated print stylesheet collapses the console to a single-column, color-preserved report for filing at shift or incident close.

### 13.5 Response Unit view

A genuinely narrower interface, since a field team consumes a decision rather than making one: chain-of-command breadcrumb collapses to their own position; no authorization controls, only a read-only confirmation of who authorized the current deployment; no FS/feature-contribution explainability stack, since a field team needs where to go, not why the model thinks so; the IAP appears read-only, reframed as assigned tasks (team, ward, route, ETA); larger touch targets for standing field use. The last-received IAP and map state persist locally on the device and remain fully readable if connectivity drops mid-deployment — the field-side counterpart of the same cache/fallback discipline required everywhere else in this architecture (Section 7.3, Section 8.1).

### 13.6 Interaction & motion

Motion only ever answers an action — a hex click animates its callout, dragging the scrubber animates color transitions. Nothing animates on load. A genuine Red alert may pulse once, meaningfully; nothing else pulses without a real state change behind it.

### 13.7 The citizen-preview panel

A small, captioned illustrative panel inside the Decision Authority console only — never a built or demoed standalone citizen product, per 13.2. It inverts to a light surface rather than the console's dark theme, because its specific illustrative purpose is outdoor/daylight legibility, the condition it actually represents. Its caption is updated from the original design to reflect Section 12.6's verified update: it now reads as an example of how the CAP payload would render once delivered through SACHET, including the Cell Broadcast channel now operational nationally alongside SMS — not only SMS, which was the implicit assumption when this panel was first designed.

### 13.8 What this section deliberately does not claim

This section does not claim a specific certified task-completion time for a duty officer using the console — any such figure is a design target to test with a short timed task against people unfamiliar with the system, not an already-measured claim, until that test has actually been run. It does not claim the color system is verified accessible until checked against a color-blindness simulator, a stated implementation requirement rather than a completed one. And it does not claim the "National View — Phase 2" tab represents built functionality — it is a deliberately greyed roadmap acknowledgment (Section 19, to be drafted), not a working aggregated-view feature.

---

## 14. Live Demo Flow & Fallback Strategy

### 14.1 Role in the document

Section 7.3 already established the feasibility-level principle: live fetch is attempted first, a curated fallback shortlist exists for resilience, and a triggered fallback is shown, not hidden. This section is the operational playbook that makes that principle actually hold up on stage — the literal step-by-step of what happens when someone types a location, and the concrete mechanisms (orchestration cadence, cold-start handling, reconnect behavior, a deliberate sensor-failure demonstration, and a pre-demo checklist) that keep the live pipeline from breaking in front of an audience.

### 14.2 The demo script, step by step

```text
1. A judge/evaluator types a place name or draws a boundary — any hilly
   Indian location, not necessarily one from the shortlist (14.3).
        ↓
2. Autonomous Region Onboarding Pipeline (Section 6) resolves the
   boundary and attempts live fetch first for every Tier 1 layer
   (DEM, land cover, forecast rainfall, geocoding — Section 8.3).
        ↓
3. Geotechnical parameters: if this location's SoilGrids-derived
   raster was not pre-fetched (Section 7.3, Section 8.2), the system
   states plainly that soil parameters are unavailable for live fetch
   and that the physics layer is running on a terrain-only estimate
   with reduced confidence — never a faked value.
        ↓
4. H3 grid generated; physics FS computed (Section 9); ML fusion run
   (Section 10); decision engine outputs risk, confidence, lead time,
   and the three threat products (Section 11).
        ↓
5. Dashboard renders (Section 13) with per-layer source/quality
   badges, live or fallback, and a stated reason behind any
   desaturated (lower-confidence) hex.
        ↓
6. If a tier reaches Orange/Red (and the cold-start guard, 14.6, does
   not suppress it), Alert Architecture (Section 12) drafts the CAP
   object and holds it for two-person authorization — it is not
   auto-published.
        ↓
7. At a moment of the presenter's choosing, a deliberate IoT
   sensor-failure demonstration (14.5) shows graceful degradation
   live, not as a hypothetical slide.
```

### 14.3 The curated demo shortlist — resilience, not a hidden pilot region

Per Section 7.3: 5–10 pre-tested locations spanning Himalayan, Western Ghats, and Northeast physiographic zones, each with a fully pre-fetched, cached dataset — including the bulk SoilGrids rasters that cannot be fetched live per coordinate (Section 7.3, Section 8.2). The critical distinction from the pilot-region design decision #1 rejected: live fetch is attempted first even for a shortlist location — the cache is the fallback path for that location, not the only path ever exercised. The shortlist exists purely as insurance against venue connectivity failure, not as the actual scope of what the system can handle; 14.8's checklist requires testing at least one genuinely novel, non-shortlist location before the real demo specifically so this distinction is not just an architectural claim but a rehearsed fact.

### 14.4 Fallback hierarchy, applied per layer

Section 8.2's data-availability matrix already lists which layers are live-per-query versus bulk-only. The fallback chain applied to each dynamic layer during a live refresh is:

```text
Local IoT observation (where instrumented, Section 12.7)
       ↓ unavailable
Satellite / regional reanalysis (ERA5-Land, SMAP)
       ↓ unavailable
Forecast estimate (Open-Meteo)
       ↓
Confidence reduction, source badge updated accordingly
```

Every step down this chain is recorded, not silently absorbed — a prediction backed by the bottom of this chain must be visibly distinguishable on the dashboard (Section 13, States) from one backed by a healthy live IoT reading, per Section 8.1's data-sourcing principles.

### 14.5 A deliberate IoT sensor-failure demonstration

One simulated sensor is deliberately taken offline mid-demo — an actual MQTT publish toggled off in front of the audience, not a staged screen change, since it is a real code path and should be shown as one:

```text
IoT publish stopped
      ↓
Sensor-health flag updates
      ↓
Fallback to satellite/forecast estimate (14.4)
      ↓
Prediction continues without crashing; dashboard's LIVE/CACHED
badge (Section 13, States) updates for the affected hex
```

This turns Section 7.3's "showing its own fallback logic live is a demo strength, not a weakness to disguise" framing into something a judge actually watches happen, rather than something only described.

### 14.6 Keeping the live pipeline demo-safe

"Real time" has not yet been defined precisely elsewhere in this document; stated here, where it matters operationally: a continuously-refreshing pipeline running at a cadence bounded by what the underlying public data actually supports — not sub-second prediction, which no input source here provides. Concretely:

- **Two independent loops, not one.** A scheduled refresh cycle matched to the rainfall/forecast API's own update interval (roughly 15–60 minutes) recomputes dynamic features, FS, and risk per hex; a separate, faster simulated-IoT stream (seconds) updates its own fields independently, without overwriting the slow loop's — two loops because the two update rates genuinely differ, not an arbitrary design split.
- **Deduplicated, bounded dynamic-layer calls.** Per-hex calls to a dynamic API are grouped by a coarse spatial key (roughly matched to the coarsest input resolution actually in use — Section 8.1, item 2) and bounded by a concurrency limit, so scoring a demo region's few hundred to few thousand hexes (14.7) does not turn into one API call per hex and trip a public rate limit.
- **Per-hex independent fallback.** One hex's live call failing falls back to its own last-known-good cached value and is tagged accordingly (14.4) — a single flaky call must never fail the whole refresh cycle.
- **Cold-start guard.** The very first cycle after a region is onboarded (Section 6) never fires an alert even if a hex starts at Orange/Red — already stated as a backend requirement in Section 12.4, restated here as the operational reason it exists: without it, onboarding a brand-new region live, on stage, would risk an alert firing before the pipeline has ever actually run.
- **Reconnect-safe push.** The dashboard always fetches a full state snapshot on connect or reconnect, before applying any incremental update on top — because venue wifi dropping mid-demo is a real, expected failure mode (Section 7.3), and a client that only applies deltas after reconnecting would show a stale, half-updated map rather than an honestly-labeled cached one.

### 14.7 Compute/H3 sizing, decided at query time

H3 resolution 8 (~0.737 km² per hex, roughly 800–920m across — Section 8.6's corrected figure, not the ~0.46 km² value an earlier pass of this section used) is the default — fine enough to distinguish village/ward-scale risk, coarse enough that a typical query area resolves to a few hundred to low thousands of hexes; resolution 7 (~5.16 km² per hex) serves as a coarser overview if the resolved area is large, with resolution 8–9 reserved for a drill-down on the highest-risk sub-area, avoiding fine-grained inference across an entire large area at once.

This sizing decision must now be made automatically from the resolved boundary's actual extent and Section 7.3's bounded ~15 km compute radius, at query time — not entered per region in a configuration file, which is exactly the mechanism decision #1 (Section 6) removed. This is the same correction pattern already applied twice in Section 13 (the chain-of-command breadcrumb and the citizen-preview font pairing): a sizing rule that used to live in the old Region Configuration Layer has to be re-derived from something the Autonomous Region Onboarding Pipeline actually computes, not left assuming a mechanism that no longer exists.

### 14.8 Pre-demo correctness checklist

- [ ] Scheduler confirmed to run one refresh cycle at a time (no overlapping cycles), with a short grace window for a late cycle
- [ ] Broadcast/push loop verified to survive a client disconnecting mid-send
- [ ] Coarse spatial-key deduplication checked against the shortlist's (14.3) actual hex centroids for unintended cross-village grouping
- [ ] Concurrency limit confirmed not to trip the rainfall/forecast API's rate limit at the shortlist's hex counts
- [ ] Per-hex fallback manually tested (kill network mid-cycle) — cycle completes, fallback tag appears, no crash
- [ ] Cold-start warm-up confirmed — first cycle after onboarding a fresh location produces zero spurious alerts even if hexes start at Orange/Red
- [ ] Snapshot/resync tested against a forced client disconnect/reconnect
- [ ] Full cycle replayed once against a historical LOEO/LORO event (Section 17, to be drafted) with a known expected outcome, checked by hand
- [ ] At least one genuinely novel, non-shortlist location tested live before the actual demo — not the shortlist alone

### 14.9 What this section deliberately does not claim

This section does not claim sub-second real-time prediction — 14.6's own definition of "real time" is the one that stands. It does not claim the shortlist locations (14.3) represent the system's real operating envelope or are somehow more validated than any other location; Section 7.1's honesty distinction between architectural region-agnosticism and empirical validation applies to shortlist locations exactly as it does to any other. And it does not claim the orchestration layer (14.6) contains any physics or ML logic of its own — it is sequencing glue, so any incorrect output surfaced during 14.8's checklist belongs to whichever module it called, not to the orchestrator itself.

---

## 15. Technical Stack

### 15.1 Role in the document

Sections 6–14 established *what* each layer must do — resolve a region, derive geotechnical parameters, run the physics and ML fusion, package alerts, render the console, survive a live demo. This section is the *with what* — the concrete libraries, services, and two deliberate swaps from the original v5 stack, plus the corrected feature count (Section 10.3), the confidence/badge fields (Sections 6, 11, 13), and the orchestration primitives (Section 14.6) that the sections above already assumed but did not name.

### 15.2 Layer-by-layer stack

| Layer | Choice | Carried from v5 unchanged? |
|---|---|---|
| Language / core | Python 3.11+ | Unchanged |
| Numerical / tabular | NumPy, Pandas | Unchanged |
| Geospatial | GeoPandas, Shapely, PyProj, Rasterio (GDAL bundled — 15.7) | Unchanged in library choice; Rasterio/GDAL now also carry the load of reading the live-fetched DEM and ESA WorldCover rasters and the bulk SoilGrids WCS export (Section 8), not just a static pilot-region DEM |
| Spatial indexing | H3 (`h3-py`, v4 API — 15.7) | Unchanged in library choice |
| ML | scikit-learn, XGBoost | Unchanged (Section 10.2) |
| Explainability | `feature_importances_` (default), SHAP (stretch goal) | Unchanged (Section 10.2, 10.7) |
| Backend framework | FastAPI | Unchanged |
| Datastore | **SQLite via GeoPackage (.gpkg) + GeoPandas** | **Swap #1 — was PostgreSQL + PostGIS (v5 Section 33–34); refined in 15.7** |
| Push / live updates | FastAPI WebSocket endpoint | New — implied by Section 13.4's silent-refresh/alert-pulse behavior and Section 14.6's reconnect-safe snapshot-then-delta requirement, not named as a discrete stack item anywhere upstream |
| Scheduling | APScheduler's `AsyncIOScheduler`, wired to FastAPI's `lifespan`, `max_instances=1` on the slow loop; a persistent `asyncio` task for the fast simulated-IoT loop | New — implied by Section 14.6's two-independent-loops requirement; pinned to a specific scheduler class in 15.7 |
| IoT simulation | MQTT, Mosquitto (or equivalent broker), Python MQTT client | Unchanged (Section 8, Section 14.5) |
| Frontend framework | React | Unchanged |
| Map rendering | **deck.gl, `H3HexagonLayer`** | **Swap #2 — was Mapbox GL / Leaflet (v5 Section 36)** |
| Base map tiles | **MapLibre GL JS via `react-map-gl/maplibre`** | **Refined in 15.7 — v5 assumed Mapbox GL; the swap to deck.gl makes this the moment to also drop Mapbox GL's post-v1 proprietary license/token requirement** |
| Charting | A charting library (sparklines, feature-contribution bars — Section 13.4) | Unchanged, library left unpinned |
| Deployment | Docker, Docker Compose, cloud VM or on-premise host | Unchanged |

### 15.3 Swap #1 — SQLite (as GeoPackage) + GeoPandas, not PostgreSQL + PostGIS

v5's Section 33–34 specified PostgreSQL + PostGIS as the datastore, with a schema of ten tables (`h3_cells`, `static_features`, `dynamic_features`, `historical_events`, `risk_predictions`, `loeo_results`, `sensors`, `sensor_readings`, `shelters`, `alerts`). That table set carries forward unchanged in shape; only the engine underneath it changes.

**Why the swap.** A hackathon-scale build queries a few hundred to low thousands of H3 hexes per region at a time (Section 14.7), not a nationwide, continuously-growing spatial dataset under concurrent write load. PostGIS's actual advantages — spatial indexing at large scale, concurrent multi-writer access, server-side spatial SQL — are built for a workload this project does not yet have. GeoPandas already performs the spatial joins and geometry operations this pipeline needs in-process (it is in the stack regardless, for DEM/WorldCover/SoilGrids raster handling — Section 8), so SQLite as the underlying row store adds zero deployment complexity (no separate database server, container, or connection pool to run alongside FastAPI) for a workload GeoPandas already handles at the application layer.

**Refined format, not just "SQLite."** Plain SQLite has no native geometry type — storing geometries as raw WKT/WKB text in an ordinary column works, but throws away spatial indexing entirely, which would make even a modest bounding-box query over `h3_cells` a full-table scan. OGC GeoPackage — itself a SQLite database with a standardized schema for geometry columns, CRS metadata, and an R-tree spatial index — is the concrete format actually used here: `GeoDataFrame.to_file(..., driver="GPKG")` / `geopandas.read_file(...)` write and read it natively, with no separate server process and no extension-loading step at runtime. This keeps the "one file, zero deployment complexity" property the swap is for, while not silently giving up spatial indexing along with PostGIS — a single `.gpkg` file per onboarded region (Section 6) is a natural fit for the region-agnostic redesign in its own right, since a region's full dataset is then a single portable artifact rather than a set of rows sharing one undifferentiated table space with every other region.

**What is explicitly given up, stated rather than left implicit.** True concurrent-write safety, and multi-instance horizontal scaling — GeoPackage's R-tree index handles the read-side spatial-query problem PostGIS's GiST index would, but SQLite's single-writer-at-a-time model is unchanged regardless of on-disk format. None of these are demo- or hackathon-relevant; a single GeoPackage file with GeoPandas-mediated access is not a permanent architectural claim, only the tool matched to the task.

**When to revisit.** If the project moves toward continuous multi-region operation at genuinely large hex counts, sustained concurrent writers (e.g. many simultaneously onboarded regions, or a production multi-agency deployment), or true horizontal scaling — the datastore should move to PostgreSQL + PostGIS at that point, not before. This is stated so the swap is not mistaken for a permanent design conviction; it is a scale-matched choice, revisited when the scale assumption it rests on stops holding, exactly as decision #5 in the section's own framing states it (unless/until scale demands it).

### 15.4 Swap #2 — deck.gl's `H3HexagonLayer`, not Mapbox GL / Leaflet

v5's Section 36 specified Mapbox GL / Leaflet as the map layer. Both render arbitrary GeoJSON polygons well, but neither is purpose-built for H3: an H3 cell would need to be converted to a GeoJSON polygon (via `h3-js`'s boundary function) before either library could draw it, and every hex-level interaction (hover, click, tier-color fill, the confidence-desaturation effect of Section 13.4, the second independent alert-resilience dot) would be built against that intermediate GeoJSON layer rather than against the H3 index directly.

**Why the swap.** deck.gl's `H3HexagonLayer` is a composite layer that takes an H3 index directly via a `getHexagon` accessor and renders it as a filled, styleable polygon with per-hex color, elevation, and pickability — the GeoJSON-conversion step is handled internally rather than something HydraSense's own frontend code has to maintain. Because deck.gl is a WebGL-based rendering layer built for large point/polygon datasets, it is also the better fit once a query resolves to the low-thousands-of-hexes case Section 14.7 already anticipates for a large query area, compared to Leaflet's SVG/Canvas-based polygon rendering.

**What this does not change.** deck.gl renders layers on top of a base map (it is not a basemap provider itself); a base map tile layer still sits underneath the `H3HexagonLayer`, consistent with Section 13.4's requirement that the base map read as a computed grid rather than false photographic precision — the literal-hexagon aesthetic Section 13.4 calls for is exactly what `H3HexagonLayer` draws by default, not an additional design constraint layered on top of a library built for something else.

**The base-map layer itself is corrected in 15.7:** v5's own Mapbox GL / Leaflet framing predates a licensing shift that makes Mapbox GL JS the wrong specific choice underneath deck.gl now, independent of the H3-rendering swap above.

### 15.5 Backend architecture, updated

```text
React frontend (deck.gl H3HexagonLayer)
        ↓  REST (fetch) + WebSocket (push)
FastAPI
        ↓
SQLite (GeoPandas-mediated spatial access)
        ↓
Python ML/physics service (Sections 9–10)
        ↓
Autonomous Region Onboarding Pipeline (Section 6)
        ↓
External APIs / datasets (OpenTopography, ESA WorldCover, SoilGrids
WCS/GEE bulk export, ERA5-Land/SMAP, Open-Meteo)
```

Endpoints, updated from v5 Section 33's list for the region-agnostic redesign — `region` replaces an assumed single pilot region as an explicit parameter throughout, and three endpoints are added for functionality Sections 6–14 already require but v5's endpoint list predates:

```text
POST /region/resolve?query=...                 (Section 6, step 1 — boundary resolution
                                                  for a typed location or drawn polygon)
GET  /risk/map?region=...&bbox=...
GET  /risk/{hex_id}/history
GET  /risk/{hex_id}/uncertainty
GET  /confidence/{hex_id}/breakdown              (Section 11.3, 13.4 — the three-factor
                                                  breakdown behind a desaturated hex)
GET  /validation/loeo
GET  /validation/loro                            (Section 10.6, 17 — LORO is the
                                                  region-agnostic claim's central evidence)
GET  /shelters/nearest/{hex_id}
WS   /live/{region}                              (Section 13.4, 14.6 — snapshot on
                                                  connect, incremental push after)

POST /alert/trigger
POST /alert/authorize                            (Section 12.4's two-person gate)
GET  /alert/feed
```

Inundation computation remains gated behind Orange/Red in backend code, not only in the UI (unchanged from v5 Section 33).

### 15.6 Core API data contract, updated

v5's Section 45 data contract predates the region-agnostic redesign and omits every field Sections 6–13 have since made load-bearing: the region-agnostic honesty framing (`has_local_calibration`, the three-factor confidence breakdown), the per-layer source/quality badges (Section 6 step 11, Section 13.4 footer), and the corrected 29-feature count (Section 10.3). Updated:

```json
{
  "hex_id": "8928308280fffff",
  "region_code": "auto-resolved-slug",
  "timestamp": "2026-09-27T14:32:00+05:30",
  "risk_score": 82,
  "tier": "RED",
  "confidence_score": 53,
  "confidence_breakdown": {
    "model_probability_factor": 71,
    "fs_uncertainty_factor": 48,
    "has_local_calibration": false
  },
  "lead_time_min": 51,
  "threat_products": {
    "risk": "RED",
    "imminent_threat": "RED in 51 min",
    "persistent_threat": "ELEVATED (3/3 windows)"
  },
  "factor_of_safety": 0.96,
  "factor_of_safety_min": 0.82,
  "factor_of_safety_max": 1.11,
  "fs_band_widened_for_no_calibration": true,
  "iot_status": "healthy",
  "instrumented_hex": false,
  "data_source": {
    "terrain": "live",
    "soil": "cached",
    "rainfall": "live"
  },
  "top_contributing_features": [
    "rainfall_6h",
    "soil_saturation_ratio",
    "factor_of_safety",
    "TWI"
  ]
}
```

`data_source` is now an object per layer rather than v5's single flat string, because Section 6 step 11 and Section 13.4's footer both require the fallback state to be visible per layer, not as one aggregate value that would hide exactly which layer fell back — the same distinction Section 14.4's fallback hierarchy draws per dynamic layer.

### 15.7 Compatibility verification pass

Per the standing instruction to verify a specific technical claim before locking it in (repeated at the top of this document-building process), every entry in 15.2 was checked against current documentation before this section was finalized, rather than carried over from habit or from v5's own age. Two entries changed as a direct result; the rest were confirmed as already the right choice, stated here so a future contributor does not re-litigate them without new information:

| Item | Verified against current sources | Result |
|---|---|---|
| SQLite as datastore | GeoPandas's native GeoPackage read/write support; GeoPackage's own R-tree spatial-index mechanism | **Refined, not reversed** — "SQLite" alone would have quietly dropped spatial indexing; GeoPackage keeps the zero-server-process property while keeping the index. 15.3 updated accordingly. |
| Mapbox GL as the base map under deck.gl | Mapbox GL JS has required a Mapbox account token for all usage, including self-hosted, since v2 (a licensing change, not a technical limitation); deck.gl's own current documentation and examples default to MapLibre GL JS (the pre-v2 open-source fork) via `react-map-gl/maplibre`, which needs no token | **Changed** — MapLibre GL JS via `react-map-gl/maplibre`, paired with a token-free basemap tile source (e.g. a free vector/raster tile service that does not require an account), replaces the implicit Mapbox GL assumption. This also removes one more external-account dependency from the demo-day failure surface Section 14 already worries about — not a functional requirement of the H3HexagonLayer swap itself, but a good moment to fix it, since the map stack is already being touched. |
| Rasterio/GDAL installation | Rasterio's official PyPI wheels for Linux (manylinux) bundle GDAL, GEOS, and PROJ — the classic "GDAL won't install" pain point most teams hit is a source-build problem, avoided entirely by installing from the prebuilt wheel | **Confirmed, clarified** — the Docker image (15.2) should install rasterio via its standard PyPI wheel rather than separately apt-installing `libgdal-dev` first; doing both risks two GDAL builds conflicting in the same container. GDAL is dropped as a separately-listed stack item in 15.2 for this reason — it is not absent, it is bundled. |
| `h3-py` API surface | Current stable `h3-py` (v4.x line) uses the renamed v4 function set (e.g. `latlng_to_cell`, `cell_to_boundary`) — the older `geo_to_h3`/`h3_to_geo_boundary` names from the v3 line are deprecated | **Confirmed, clarified** — any code written against this stack should target the v4 API by name; a contributor copying an older Stack Overflow snippet or v3-era tutorial would otherwise introduce a dependency mismatch. Worth stating explicitly since Sections 6 and 9 both describe H3 operations in prose without naming specific function calls. |
| APScheduler for the slow loop | Current recommended pattern for APScheduler under FastAPI is `AsyncIOScheduler` wired to FastAPI's `lifespan` context (started on startup, shut down on shutdown), with `max_instances=1` set on the job to prevent overlapping runs | **Confirmed, pinned to a specific class** — `AsyncIOScheduler` (not the thread-based `BackgroundScheduler`, which would fight FastAPI's own event loop) is the correct choice, and `max_instances=1` is not an incidental setting: it is the literal mechanism behind Section 14.8's first checklist item ("scheduler confirmed to run one refresh cycle at a time"), so it belongs in this section by name rather than left for whoever implements Section 14's checklist to discover on their own. |
| scikit-learn / XGBoost | Both remain current, actively maintained, and mutually compatible via XGBoost's scikit-learn-compatible estimator API (`XGBClassifier`) | Confirmed, no change |
| FastAPI, React, Docker/Docker Compose, MQTT/Mosquitto | All remain current and standard for their respective roles; no compatibility or licensing issues surfaced | Confirmed, no change |

### 15.8 What this section deliberately does not claim

This section does not claim SQLite/GeoPackage or deck.gl are the objectively superior choice in general — 15.3 and 15.4 both state the specific, scale-bounded reasoning behind each swap and the conditions under which the original v5 choice (PostGIS, Mapbox GL/Leaflet) would become the right one again. It does not claim the endpoint list in 15.5 is final or exhaustive — Section 16 (Build Plan & Milestones, to be drafted) may surface additional endpoints as implementation sequencing is worked out. It does not claim the charting library left unpinned in 15.2 is a gap in the architecture rather than a genuinely low-stakes choice deferred to implementation time, unlike the datastore and map-rendering choices in 15.3–15.4, which the architecture does take a position on. And 15.7's verification pass does not claim to be exhaustive against every possible future compatibility break — it establishes that each item was checked once, now, against current sources, not that the stack is permanently immune to upstream changes; a build-time dependency check (e.g. `pip list --outdated`, a lockfile audit) at Section 16's implementation stage remains the actual safeguard against drift after this point.

---

## 16. Build Plan & Milestones

### 16.1 Relationship to v5's module sequence

v5's Section 43 ("Implementation Sequence") already established the right *shape* for this section — dependency order rather than a fixed calendar, because each stage genuinely requires the outputs of the one before it. That shape is kept. What changes, in every stage, is the same substitution decision #1 (Section 6) makes everywhere else in this document: a step that used to read "for the target/pilot region" becomes a step that builds the *mechanism* that works for any region, and a step that used to read "train on the two-region dataset" becomes "train on the pooled multi-region dataset, with LORO as the gate before any region-agnostic claim is presented." Stage numbers below are dependency stages, not calendar weeks — a team should map them onto its actual hackathon timeline (ideation round, build phase, grand-finale demo, whatever that team's specific schedule is), not treat "Stage 3" as "week 3."

### 16.2 Stage 0 — Data-access lockdown (blocker before any pipeline code is written)

This stage exists only because of a fact decision #3 already forced onto this document: SoilGrids' REST point-query API is currently paused, so geotechnical data cannot be fetched live per coordinate the way the DEM, land cover, and forecast layers can (Section 7.3, Section 8.2). Building against a live-SoilGrids assumption and discovering the outage mid-build would be far more expensive than confirming it up front.

- [ ] Confirm live reachability of every Tier 1 source (Section 8.3): OpenTopography DEM, ESA WorldCover, Open-Meteo forecast, the geocoding/boundary service
- [ ] Pre-fetch bulk SoilGrids rasters via WCS or Google Earth Engine for at least the demo shortlist's bounding boxes (Section 14.3) — this cannot be deferred to a later stage, since Stage 1's geotechnical-parameter derivation depends on it
- [ ] Re-check SoilGrids' REST status once before this stage closes, per the standing verify-before-locking-in instruction — if it has been restored, Section 8.2's data-availability matrix and Section 14.3's shortlist rationale should be revisited rather than left describing a workaround that's no longer necessary

**Milestone:** every Tier 1 layer is reachable, and the demo shortlist's geotechnical rasters exist on disk before Stage 1 begins.

### 16.3 Stage 1 — Autonomous Region Onboarding Pipeline

The v5 equivalent ("Data and Spatial Foundation") assumed a single target region configured once. Here, the deliverable is the pipeline itself (Section 6), built to run identically for *any* queried location:

- Boundary resolution from a typed place name or drawn polygon
- Live DEM fetch and terrain-derivative computation (slope, aspect, TWI, TRI, flow accumulation, HAND — Section 8)
- ESA WorldCover land-cover fetch
- Geotechnical parameters derived from the Stage-0 SoilGrids rasters via the pedotransfer correlations (texture/bulk density → cohesion/friction angle — Section 9.2), replacing v5's manual lookup table entirely
- H3 grid generation sized from the resolved boundary's actual extent (Section 14.7), not a config value
- Historical-context check: is this location GSI-mapped, and does a usable local event inventory exist (Section 8.3 Tier 3)
- GeoPackage schema (Section 15.3) for everything this stage produces

**Milestone:** a previously-untested hilly place name, typed in, produces a resolved boundary, an H3 grid, and a fully-populated static feature table with zero manual configuration — the region-agnostic claim demonstrated at the pipeline level, before any physics or ML sits on top of it.

### 16.4 Stage 2 — Dynamic Layer and Physics Core

- Dynamic rainfall/soil-state ingestion (ERA5-Land/SMAP/Open-Meteo) with the per-layer fallback chain wired in from the start (Section 14.4), not added later
- Infinite-slope Factor of Safety model and its uncertainty band (Section 9), including the "no local calibration → widened FS band" behavior already reflected in the API contract (`fs_band_widened_for_no_calibration`, Section 15.6)
- Historical event inventory compiled as a *pooled*, multi-region set from the start (Section 10.4) — not a single region's inventory with others added later, since the pooling itself is what the training and validation strategy in Stages 3–4 depend on

**Milestone:** FS computes correctly and produces a sane, physically-plausible number and uncertainty band for at least one region with a well-documented real event, checked by hand before any ML is trained on top of it.

### 16.5 Stage 3 — ML Fusion (Trained Candidate, Not Yet Validated)

- Event-centered temporal sampling (Section 10.5) applied across the pooled event set
- The corrected 29-feature unified table (Section 10.3), including `has_local_calibration`
- XGBoost training on the pooled multi-region dataset (Section 10.4)

This stage's output is explicitly a *candidate* model, not a validated one — Section 10.6 is the reason LOEO/LORO get their own stage rather than being folded into training. A team should resist the temptation to treat "the model trains and produces plausible-looking scores" as a finished milestone; it is Stage 3's milestone, and Stage 4 is what actually tests the claim this document is making.

**Milestone:** a single trained XGBoost model exists over the full pooled feature table, with training-time sample provenance (which event, which region, which lead-time offset) preserved per row — required for Stage 4's leave-one-event-out and leave-one-region-out splits to be implemented correctly (Section 10.5's warning about partial-event leakage applies here).

### 16.6 Stage 4 — Validation: LOEO and LORO (the gate before any region-agnostic claim is shown to a judge)

- Implement Leave-One-Event-Out validation
- Implement Leave-One-Region-Out validation, holding out every event and timestep belonging to a region together (Section 10.5, Section 10.6)
- Run both; record detection rate, false-positive rate, and timing error — for LORO, per held-out region, not only as one aggregate figure across all regions
- Document and freeze these results before any deployment or accuracy claim is made, per v5 Stage 7's own principle — but applied here, one stage earlier than v5 placed it, because in this architecture the validation result is not a final sign-off step, it is the actual evidence behind the document's central claim (Section 1, Section 7.1, Section 10.6)

This is the single go/no-go gate in the whole build plan. If LORO shows materially weaker performance in under-represented regions, that is a finding for Section 18 (Scientific Limitations, to be drafted) to state honestly — not a result to quietly omit or to keep iterating on until it disappears. Section 10.6 already commits this document to reporting it either way.

**Milestone:** LOEO and per-region LORO results exist, are recorded, and are frozen for the reporting period before Stage 6 (dashboard) wires up anything that displays them.

### 16.7 Stage 5 — Decision Engine, Alerts, Backend Services

- Risk score, tiering, and the three-factor confidence score (Section 11)
- Lead-time estimation and the three threat products (Section 11, Section 15.6)
- FastAPI endpoints per Section 15.5, including `/validation/loro` surfacing Stage 4's frozen results
- CAP alert generation with the two-person authorization gate (Section 12.4) — never auto-published
- Shelter lookup

**Milestone:** a full prediction cycle — query in, risk score, confidence breakdown, lead time, and a drafted (unpublished) CAP object out — runs end-to-end against the backend alone, with no frontend involved yet.

### 16.8 Stage 6 — Dashboard and Frontend

- MapLibre GL JS via `react-map-gl/maplibre`, with deck.gl's H3HexagonLayer (Section 15.4)
- Risk, confidence, and lead-time panels; the feature-contribution panel (Section 10.7)
- Per-layer source/quality badges and desaturated low-confidence hexes (Section 13.4, Section 14.4)
- A validation/data-health panel surfacing Stage 4's frozen LOEO/LORO summary — this is what turns Section 10.6's "LORO should be the first number shown to a judge" from a documentation intent into something actually on screen

**Milestone:** the dashboard correctly distinguishes live from cached/fallback badges and renders a visibly lower-confidence hex for at least one live query and one deliberately triggered fallback (Section 14.5).

### 16.9 Stage 7 — Demo Readiness

This stage is Section 14.8's pre-demo checklist, not a separate list duplicated here — Section 14 was drafted in enough operational detail that restating it would drift out of sync with it over time. The stage exists in this build plan to make one thing explicit: demo readiness is its own dependency-ordered stage that comes *after* Stage 6, not a parallel afterthought squeezed in alongside frontend work.

**Milestone:** every item in Section 14.8 passes, including the genuinely novel non-shortlist location tested live before the actual demo.

### 16.10 What this section deliberately does not claim

This section does not propose a calendar — no week numbers, no day counts — because this document has no visibility into which hackathon phase (ideation round, build phase, grand-finale window) the reader is currently planning against; the stages are ordered by genuine dependency, and mapping them onto real dates is left to the team. It does not claim the stages must run strictly sequentially with no overlap — dashboard scaffolding (Stage 6) can reasonably start before Stage 4's validation is frozen, for instance, so long as the panels that display frozen validation results aren't wired to real numbers until Stage 4 actually produces them. And it does not claim Stage 4's LOEO/LORO methodology is fully specified here — the metrics, spatial-block validation, and hazard-type split belong to Section 17 (Validation Strategy, to be drafted), which this stage's milestone depends on but does not itself define.

---

## 17. Validation Strategy

### 17.1 Relationship to v5's own validation design

Unlike most of this document, this section is not a redesign of v5's thinking — v5's Section 25 already contained Leave-One-Region-Out validation, a hazard-type split, spatial block validation as a required (not future) check, and an explicit statement of the design's own known risks, and its Section 26 already argued for event/spatial/temporal holdout over random pixel splits. That material anticipated almost everything the region-agnostic redesign needs from a validation strategy. What this section does is carry it forward with one correction and two additions: the correction is that every reference to "the region's configuration" is updated to mean whatever the Autonomous Region Onboarding Pipeline (Section 6) actually derives for that region, since v5's manual region-config layer no longer exists; the two additions are a validation check for the confidence score's third factor (17.8) and an explicit statement of what gets frozen together as one package (17.9), both made necessary by decisions this document has already locked in (Section 1, Section 11) that v5 did not need to account for.

### 17.2 Leave-One-Event-Out (LOEO)

```text
Training:  All events except Event E
Validation: Event E — every timestep of E held out
```

Process: remove all samples belonging to E; train on every remaining event; run prediction through E's observed timeline; check whether Orange/Red was reached before or during the event; measure timing error; repeat for every event in the pooled dataset (Section 10.4).

Metrics:

- **Classification:** recall/detection rate, precision, F1, false-positive rate, ROC-AUC where meaningful, PR-AUC for imbalanced cases
- **Probability quality:** Brier score, calibration
- **Warning performance:** detection rate, false alarm rate, mean/median/worst-case timing error, event-level lead time

### 17.3 Leave-One-Region-Out (LORO) — the central evidence for the region-agnostic claim

LOEO alone only shows the model generalizes across events *drawn from regions it has already seen in training*. It does not show HydraSense works as a genuinely region-agnostic system — and per Section 10.6, that is precisely the claim this document is not allowed to make on LOEO alone.

```text
Training:   All events from all regions except Region R
Validation: All events from Region R — held out entirely, every
            event and timestep, including from feature-derived
            pooled statistics
```

Process: select Region R; remove every event and timestep belonging to R; train on all remaining regions' pooled events; run prediction through R's observed event timelines using only R's own auto-derived terrain, land cover, and SoilGrids-derived geotechnical parameters (Section 6, Section 9.2) — nothing about R that the Autonomous Region Onboarding Pipeline would not compute for a genuinely new location; apply Section 17.2's full metric set to R's held-out events; repeat for every region with enough events to make the fold meaningful.

**Reporting requirement, not optional:** per Section 16.6, LORO results are reported per held-out region, not only as one pooled figure across all regions. A single aggregate LORO number can hide the exact asymmetry Section 10.4 already predicts — strong performance on a well-documented region (e.g. Western Ghats, given denser recent event documentation) averaged against weak performance elsewhere would produce a misleadingly healthy headline figure.

**Realistic expectation, stated up front rather than discovered late:** LORO performance will plausibly be weaker than LOEO performance, and that is an expected property of the design, not a failure to fix before reporting. The honest claim this document commits to is "the architecture is region-agnostic and demonstrates measurable, if imperfect, cross-region transfer" — never "the model performs identically everywhere." Section 17.9 says explicitly that a large LOEO/LORO gap is a Section 18 finding, not a result to iterate on until it quietly disappears.

### 17.4 Hazard-type split — flood and landslide reported separately

Every metric in 17.2 and 17.3 is computed and reported separately for flood events and for landslide events, never only as one combined figure. A strong joint PR-AUC can mask a weak result on one hazard type — the corrected 29-feature table (Section 10.3) carries flood-relevant terrain features (`flow_accumulation`, `hand_m`, `curve_number`) alongside the landslide-oriented ones precisely so this split is measurable rather than structurally impossible. The validation panel (Section 13, wired up in Section 16.8) shows the combined figure and the per-hazard breakdown together — never the combined figure alone.

### 17.5 Spatial block validation — required, not a future item

Event-based holdout (17.2, 17.3) does not catch leakage between geographically adjacent H3 hexes that share near-identical static features even when they belong to different events — a model can score well by essentially memorizing "this terrain shape means risk," a weaker claim than "this terrain-plus-hazard combination predicts an actual event."

```text
1. Partition each region's H3 hexes into spatial blocks — contiguous
   clusters of neighboring hexes, sized larger than the spatial
   autocorrelation range of the static features.
2. Hold out entire blocks, not individual hexes, for validation.
3. Train on all hexes outside the held-out blocks.
4. Test on the held-out blocks' events.
5. Compare against the LOEO/LORO results (17.2, 17.3): a large gap
   between event-based and spatial-block performance indicates the
   model is partly learning static terrain patterns rather than the
   dynamic hazard signal.
```

This check is run and reported even if the result is unflattering — it is the check most likely to reveal whether reported accuracy is inflated by spatial autocorrelation rather than genuine predictive skill.

### 17.6 Known validation risks, stated rather than assumed away

- **GSI-susceptibility circularity.** `gsi_susceptibility_class` (Section 10.3) is itself partly derived by GSI from the same historical landslide inventory this document uses to construct labels. Using an inventory-informed susceptibility class to predict inventory-derived events risks inflating reported metrics through mild circularity. Where feasible, model performance is reported both with and without `gsi_susceptibility_class` included, to show how much of the model's skill depends on this one feature.
- **Negative-sampling assumption.** Non-event cells are sampled as negatives (Section 10.5) on the assumption that absence from the inventory means absence of a real event. GSI's inventory is incomplete outside its ~21 mapped districts (Section 4), so some "negative" samples in less-covered regions may be unrecorded positives rather than true negatives — a known issue in landslide ML more broadly. This is stated as a limitation, particularly for any region outside GSI's mapped coverage, rather than left implicit.

### 17.7 Why random pixel or random row splits are not enough

Nearby samples from the same event are highly correlated — a training row and a "held-out" test row can share the same event, the same rainfall pulse, and near-identical terrain, which inflates apparent performance without demonstrating real generalization. This is why 17.2–17.5 layer event-based, region-based, and spatial-block holdout together rather than relying on any single one of them, and why none of the three is treated as optional.

### 17.8 Validating the confidence score's third factor

Section 11's confidence score has three factors: model-probability skew, FS-uncertainty width, and `has_local_calibration` — the factor decision #2 (Section 1) makes load-bearing, since a region with no local calibration must show visibly lower confidence rather than the same confidence as a GSI-mapped region. LORO gives a direct way to check this rather than taking it on faith: during each LORO fold, the held-out region necessarily has `has_local_calibration = false` for that fold, since its own calibration data was excluded from training by construction. The check: compare the confidence-score distribution the model actually produces for the held-out region against the distribution for calibrated regions at a similar predicted risk level (via the `confidence_breakdown` object, Section 15.6). If the held-out region's confidence is not systematically lower, the third factor is not doing the honesty work Section 1 requires of it, and that is itself a finding for Section 18 — not something to patch by manually reweighting the confidence formula until the LORO check happens to pass.

### 17.9 What gets frozen, and when

Per Section 16.6, the outputs of 17.2–17.6 and the check in 17.8 are recorded and frozen together as one package at Stage 4, before Stage 6's dashboard wires up anything that displays them (Section 13, Section 16.8) and before the `/validation/loeo` and `/validation/loro` endpoints (Section 15.5) serve anything beyond placeholder responses. Freezing them together, rather than piecemeal as each check happens to finish, is what prevents a later, worse LORO run from being quietly dropped in favor of an earlier, better-looking one.

### 17.10 What this section deliberately does not claim

This section does not claim that LOEO, LORO, and spatial-block validation together eliminate all leakage risk — the spatial-block size in 17.5 is a judgment call sized against an estimated autocorrelation range, not a value this document proves optimal. It does not claim the "LORO is expected to be weaker than LOEO" framing in 17.3 excuses a genuinely broken result — a very large gap between the two, or a hazard-type split (17.4) showing one hazard essentially unlearned, is still a real limitation for Section 18 to state plainly, not a result the framing is meant to soften. And it does not claim 17.8's confidence-factor check is a replacement for LORO's own primary metrics (17.3) — it is a secondary, honesty-specific check layered on top of LORO, not an alternative to it.

---

## 18. Scientific Limitations

### 18.1 Role and relationship to v5

v5's Section 49 listed eight limitation categories as a bare, unelaborated list. This section is where each receives the substance this document has already built up elsewhere, rather than staying a checklist a judge could ask about and get a thin answer to. Each limitation below points back to where it was first established — limitations are not new to this section; Section 18's job is to gather them, grade severity where that's knowable, and state plainly which ones this project can mitigate versus which are structural given the current data landscape.

### 18.2 Small pooled event dataset

Section 10.4 commits to a pooled multi-region training strategy rather than a fixed dual-pilot dataset, because event-level completeness (exact date, time, coordinates) — not geographic reach — is the actual bottleneck. GSI's own inventory (~91,000 events, Section 4) is the largest available source, but the great majority are landslide-only and concentrated in mapped districts; flood events with village-level ground truth are scarcer still. XGBoost (Section 10.2) was chosen partly because it tolerates small, imbalanced datasets, but no model choice erases the ceiling a genuinely small labeled dataset places on what LOEO/LORO (Section 17) can demonstrate — which is why Section 17.9 freezes results honestly rather than iterating until a small-dataset result looks better than the data actually supports.

### 18.3 Simulated guidance and sensor signals

Two categories of "simulated" input are already named in Section 3's "is not" list and Section 10.3's feature table (`simulated_ffgs_signal`, `simulated_gsi_signal`, `iot_anomaly_flag`) but not yet stated together as a limitation: SAsiaFFGS and GSI operational feeds are not actually integrated — no institutional data-sharing access exists for a hackathon team, so these are software-simulated stand-ins, clearly labeled rather than presented as live integrations; and IoT sensor readings (Section 14.5's deliberate failure demo) are simulated MQTT publishes, not a real physical sensor network. Both are legitimate placeholders for a system designed to accept real feeds later, but every dashboard element or verbal claim touching these must say "simulated" plainly rather than let a viewer assume live institutional integration.

### 18.4 Geotechnical parameter uncertainty

Already stated in Section 7.2: SoilGrids-derived pedotransfer correlations (texture/bulk density → cohesion/friction angle) are legitimate engineering-grade screening estimates, but the standard correlation tables were largely developed for temperate soils, and Indian hill terrain frequently has laterite and deeply weathered residual soils that don't map cleanly onto them. This is the specific, named reason Section 9's FS output is an index with an uncertainty band rather than a precise geotechnical design value — and why that band widens further in regions with no local historical calibration (Section 9.2, Section 11).

### 18.5 Forecast uncertainty

Not yet stated elsewhere as its own limitation: Open-Meteo's forecast skill (the fallback tier in Section 14.4's chain) degrades with lead time the way any NWP-derived rainfall forecast does — a 1-hour-ahead estimate is materially more reliable than a 24-hour-ahead one, and the convective, highly localized rainfall that actually triggers flash floods in hill terrain is intrinsically harder for global/regional models to resolve than broad frontal rainfall. The lead-time estimate (Section 11) therefore compounds forecast uncertainty with FS uncertainty (18.4) rather than sitting independently of it — the example `lead_time_min: 51` in Section 15.6 inherits uncertainty from both, and should never be presented, on the dashboard or verbally, as a precise countdown.

### 18.6 H3 spatial aggregation

Resolution 8 (~0.737 km² per hex, Section 14.7 and Section 8.6) is a deliberate choice, but it is still a discretization: real slope-stability and drainage behavior varies continuously, not in hexagonal steps, and a hex's risk score is a single value standing in for everything physically happening inside that area. A village straddling two adjacent hexes with different scores has no single "the village's risk" — a structural property of the H3 approach (Section 8), not a bug, and the dashboard (Section 13) should not imply finer resolution than the underlying computation actually has.

### 18.7 Simplified inundation

Section 3 already states this is not a full hydrodynamic flood simulator. The inundation layer gated behind Orange/Red (Section 15.5) is a simplified, terrain-derived flood-extent approximation, not a 2-D shallow-water hydrodynamic model with surveyed channel geometry — the kind C-FLOOD requires, and exactly why C-FLOOD (Section 4) covers only a handful of large lowland basins it has that geometry for. HydraSense trades hydrodynamic accuracy for something computable with zero manual per-region surveying, the same trade-off the region-agnostic redesign makes elsewhere — stated here explicitly rather than left for a judge to surface with a pointed question about flood-extent accuracy.

### 18.8 Exposure and impact omitted in this phase

Also already scoped out in Section 3 and Section 4: this phase produces a hazard estimate (will this location become dangerous, how soon, how confident), not an exposure or impact estimate (how many people, which structures, what value is at risk there). Restated here as a limitation because a hazard-only system, however accurate, cannot by itself prioritize which of several simultaneously at-risk hexes deserves the first evacuation resource — that prioritization is Phase 2 scope (to be drafted in Section 19), not something this phase's output should be read as already providing.

### 18.9 Limited geographic generalization — the central one

This is the limitation every other section of this document has already been built around, not one discovered here for the first time. Section 1's core design principle, Section 7.1's two-claims table, Section 10.4's training asymmetry, Section 10.6's reason LORO exists, and Section 17.3's per-region reporting requirement all exist because of one fact: a region with no local historical event data has genuinely less validated confidence behind its output than a GSI-mapped region does, and no amount of architectural elegance in the onboarding pipeline (Section 6) changes that. What this section adds: this limitation does not shrink over the course of a hackathon build — it shrinks only as real event data accumulates for more regions over years. GSI's own nationwide-coverage target, with a national mandate and institutional access this project does not have, is 2030 (Section 4). Framing the region-agnostic architecture as a head start on a problem that takes years to fully solve — not as a solved problem — is the honest version of this claim.

### 18.10 Severity, stated plainly rather than left for a judge to weigh alone

- **Structural, not fixable within this project's scope:** 18.9 (limited geographic generalization) and 18.4 (temperate-soil pedotransfer correlations) — limits of the underlying scientific/data landscape, not of this implementation's care.
- **Mitigated by design, not eliminated:** 18.5 (forecast uncertainty) and 18.6 (H3 discretization) are carried through as uncertainty bands and confidence scores (Section 11) rather than a deceptively precise single number — the limitation persists, but it is not hidden.
- **Scoped out deliberately, not overlooked:** 18.7 (simplified inundation) and 18.8 (exposure/impact omission) are phase boundaries already stated in Section 3, not gaps discovered late.
- **Fully disclosed by labeling:** 18.3 (simulated signals) requires only that "simulated" is never allowed to read as "live" — an execution discipline, not an unsolved technical problem.
- **Bounded by available data, addressed by LORO:** 18.2 (small pooled dataset) is why Section 17's validation strategy takes the shape it does — LORO does not make the dataset bigger, but it stops a small dataset from producing an inflated, unearned confidence claim.

### 18.11 What this section deliberately does not claim

This section does not claim these eight limitations are exhaustive of every way HydraSense could be wrong — they are the limitations this document's own design decisions have already surfaced through Sections 1–17, not the output of an independent adversarial review. It does not claim 18.10's severity grouping is a formal risk methodology; it is a plain-language answer to "which of these should I worry about most," not a scored framework. And it does not claim that stating a limitation here discharges the obligation to keep restating it wherever it becomes relevant — Section 1's confidence-per-region framing, for instance, is a live UI behavior (Section 13), not something that becomes true just because this section names it.

---

## 19. Future Roadmap

### 19.1 Relationship to v5's phased roadmap

v5's Section 52 already laid out a five-phase roadmap; this section keeps that shape and updates each phase for what has already changed elsewhere in this document. The biggest update: Phase 1 now includes the Autonomous Region Onboarding Pipeline and LORO as core deliverables of the hackathon submission itself (Sections 6, 10.6, 17.3), not future work — and spatial-block validation, which v5 listed under Phase 2, has already been promoted to a required Section 17.5 check, so it is removed from the roadmap below rather than duplicated in two places.

### 19.2 Phase 1 — this document's own scope, restated for continuity only

H3 spatial framework (Section 8) + Autonomous Region Onboarding Pipeline (Section 6) + terrain/land-cover/geotechnical derivation (Sections 6, 9) + dynamic rainfall/soil layer with fallback chain (Section 14.4) + physics FS with uncertainty (Section 9) + pooled-training XGBoost fusion (Section 10) + LOEO and LORO validation (Section 17) + three-factor confidence score (Section 11) + lead-time estimation (Section 11) + CAP-compliant alerting with two-person authorization (Section 12). No new content in this subsection — it exists so the roadmap reads as a continuation of something already built, not a wishlist floating separately from it.

### 19.3 Phase 2 — Research Expansion

- **AHP (Analytic Hierarchy Process) comparison** — a structured expert-weighting approach compared against the physics+ML fusion approach, to characterize where the two methods agree and diverge
- **MaxEnt susceptibility modeling comparison** — a species-distribution-style presence-only model, commonly used in landslide susceptibility literature, run as an alternative susceptibility layer to compare against the SoilGrids-derived physics approach (Section 9.2)
- **Extended Random Forest comparison** — Section 10.8 already keeps Random Forest as a baseline for sanity-checking feature importances; Phase 2 extends this into a full comparative study rather than a single sanity check
- **Satellite SAR-based validation** — Sentinel-1 change-detection cross-checks against predicted landslide events, as an independent validation signal that doesn't depend on the same historical inventories LOEO/LORO already use (partially addressing the negative-sampling risk named in Section 17.6)
- **Exposure module** — population, schools, hospitals, roads, bridges, buildings, power infrastructure, communication infrastructure, and shelters, sourced from WorldPop and OpenStreetMap; conceptually `Risk = Hazard × Exposure × Vulnerability`. This is explicitly roadmap functionality, not implemented in this document's scope (Section 18.8), included here so the shape of the eventual exposure layer is on record rather than left unspecified

### 19.4 Phase 3 — Advanced Prediction

- **LSTM/GRU sequence models** — Section 10.8 already states the precondition this phase depends on: the pooled event count is not yet large enough to justify a genuine temporal sequence model over the event-centered snapshot sampling of Section 10.5, and introducing it prematurely risks overfitting on a training strategy already stretched thin by pooling across regions. This phase begins only once that precondition is actually met, not on a fixed timeline.
- **Probabilistic forecasting** — full predictive distributions rather than the point risk scores Section 11 currently outputs
- **Higher-resolution soil moisture products** as they become publicly available, replacing or supplementing the current ERA5-Land/SMAP tier (Section 14.4)
- **Real IoT deployment** — replacing the simulated MQTT stream (Section 14.5, Section 18.3) with an actual physical sensor network

### 19.5 Phase 4 — Cascading Risk

The architecture already performs multi-hazard fusion at its core (flood and landslide share the same pipeline). A future version can explicitly model the dependency chain between them, rather than only fusing two independently-computed scores:

```text
Extreme rainfall
       │
       ├──────────────→ Runoff concentration
       │                       ↓
       │                  Flash flood
       │
       └──────────────→ Soil saturation
                               ↓
                          Landslide
                               ↓
                     Road / channel blockage
                               ↓
                    Increased flood impact
                               ↓
                       Evacuation delay
```

This counts as a genuine cascading-hazard model only once these dependencies are explicitly modeled — combining two independently-computed risk scores is not the same claim, and should not be presented as if it were.

### 19.6 Phase 5 — Operationalization, and the honest answer to how Section 18.9 narrows

- Real institutional data-sharing agreements with SAsiaFFGS, GSI, and IMD, replacing the simulated adapters (Section 3, Section 18.3)
- Real physical sensor deployment, replacing the simulated IoT stream (Section 18.3)
- Real CAP/SACHET distribution integration, beyond the current authorized-but-unpublished draft object (Section 12.4)
- **Continuous validation** — LOEO and LORO re-run as new events accumulate, rather than the one-time freeze Section 17.9 describes for this document's own reporting period
- The actual mechanism by which Section 18.9's structural limitation narrows over time, stated plainly rather than left implicit: as real, event-level-complete data is obtained from more regions, `has_local_calibration` becomes true for more of hilly India, and the confidence gap between calibrated and uncalibrated regions that Section 17.8 checks for should measurably shrink release over release. This is the honest answer to "how does the region-agnostic claim get stronger over time" — not a claim that it is already uniformly strong, which Section 1 and Section 7.1 already rule out.

### 19.7 What this section deliberately does not claim

This section does not attach calendar dates to any phase, for the same reason Section 16.10 gives for the build plan: this document has no visibility into what timeline or funding a team pursuing these phases would have. It does not claim the phases are strictly sequential — the exposure module (Phase 2) and LSTM work (Phase 3) don't depend on each other and could proceed in parallel once Phase 1's core is stable, for instance. And it does not claim Phase 5's continuous validation removes the need for Section 17's frozen validation package — a frozen snapshot per reporting period remains necessary; continuous validation just repeats that freeze on an ongoing cadence instead of doing it once.

---

## 20. Appendices

### 20.1 Final architecture diagram

Adapted from v5's Section 53: the entry point is now the Autonomous Region Onboarding Pipeline rather than a pre-configured region, and the output side carries the three-factor confidence breakdown rather than a single confidence number.

```text
                    EXISTING SYSTEMS
       ┌────────────────────────────────────┐
       │ SAsiaFFGS │ GSI │ CWC │ EO │ NWP  │
       └───────────────────┬────────────────┘
                           ↓
       AUTONOMOUS REGION ONBOARDING PIPELINE (Section 6)
   boundary resolve → DEM → terrain derivatives → land cover
   → SoilGrids-derived geotechnical params → H3 grid →
   dynamic layer → historical-context check
                           ↓
                     H3 MICRO-GRID
                           ↓
        ┌──────────────────┴──────────────────┐
        │                                     │
        ↓                                     ↓
 STATIC SUSCEPTIBILITY                  DYNAMIC HAZARD
        │                                     │
 slope / elevation                       rainfall
 TWI / TRI / HAND                        intensity
 drainage / flow acc.                    antecedent rain
 LULC / NDVI                             soil saturation
 history (where it exists)               IoT (simulated)
 GSI class (optional-null)               guidance signals (simulated)
        │                                     │
        └──────────────────┬──────────────────┘
                           ↓
                  INFINITE SLOPE MODEL
                           ↓
              FS / FS RANGE (widened if uncalibrated)
                           ↓
          XGBOOST FUSION (pooled multi-region training)
                           ↓
        ┌──────────────────┼───────────────────┐
        ↓                  ↓                   ↓
    RISK 0–100    3-FACTOR CONFIDENCE     EXPLAINABILITY
        │          (model / FS / has_local_calibration)
        ↓
       FORECAST PROJECTION
              │
              ↓
        TIME-TO-RED
              │
              ↓
       GREEN/YELLOW/ORANGE/RED
              │
      ┌───────┼─────────┐
      ↓       ↓         ↓
   H3 MAP  INUNDATION  ALERT (2-person authorization)
                      │
                      ↓
             CAP / SACHET / SMS
                      │
                      ↓
           DASHBOARD (source/quality badges,
             LOEO/LORO panel per Section 17)
```

### 20.2 One-sentence final definition

v5's Section 54 version referenced a "Region Configuration Layer" that no longer exists in this architecture (Section 6). Corrected:

> **HydraSense is a region-agnostic, hyper-local flash-flood and landslide decision-support layer that downscales broader guidance into H3 village/ward-scale risk by fusing terrain susceptibility, rainfall, soil state, physics-based slope stability, local observations, and ML — deployable to any hilly region in India through its Autonomous Region Onboarding Pipeline rather than rebuilt or reconfigured per location — while explicitly communicating uncertainty, per-region calibration status, and forecast-derived time-to-RED through actionable alerts.**

### 20.3 Final development principles

v5's Section 55 principle still holds unchanged, and this document adds one more of its own — the two are stated together because both are load-bearing, not because the second replaces the first:

> **Every number shown to a stakeholder or end user should come from a defined computation, every data source should be labelled honestly, and every performance claim should be tied to a validation method.** That principle is more important than adding another model.

> **Architectural region-agnosticism and empirically validated accuracy are different claims, and this system states which one it is making, per region, at prediction time — never letting the first stand in for the second.** That principle is the reason this document's confidence score, LORO validation, and per-layer source badges all exist.

### 20.4 Appendix A — Suggested project folder structure

Adapted from v5's Appendix A: the `regions/` folder of manually-authored per-region YAML files and the geotechnical lookup table are removed entirely — decision #1 (Section 6) replaced both with code, not configuration.

```text
hydrasense/
│
├── backend/
│   ├── main.py                      # scheduler.start() wired on startup (Section 14.6)
│   ├── routes/
│   │   └── live.py                  # WS /live/{region}, snapshot-on-connect (Section 15.5)
│   ├── services/
│   │   ├── orchestrator.py          # refresh_cycle() — live ingestion sequencing (Section 14.6)
│   │   ├── connection_manager.py    # WebSocket broadcast (Section 14.6)
│   │   └── tier_state.py            # previous-tier tracking, cold-start guard (Section 14.6)
│   ├── models/
│   └── schemas/
│
├── onboarding/                      # Autonomous Region Onboarding Pipeline (Section 6)
│   ├── boundary_resolver.py         # place name / polygon → boundary
│   ├── dem_fetch.py
│   ├── landcover_fetch.py
│   ├── soil_derivation.py           # SoilGrids bulk raster → pedotransfer cohesion/friction angle
│   ├── h3_grid.py                   # sized from resolved extent, not a config value (Section 14.7)
│   └── historical_context_check.py  # GSI-mapped? local inventory? → has_local_calibration
│
├── ml/
│   ├── preprocessing.py
│   ├── features.py                  # 29-feature table (Section 10.3)
│   ├── train_xgboost.py             # pooled multi-region training (Section 10.4)
│   ├── validate_loeo.py
│   ├── validate_loro.py             # per-region reporting (Section 17.3)
│   ├── explain.py
│   └── model.pkl
│
├── physics/
│   ├── infinite_slope.py
│   └── uncertainty.py               # widens band when has_local_calibration is false
│
├── geospatial/
│   ├── dem_processing.py
│   ├── h3_grid.py
│   ├── drainage.py
│   ├── twi.py
│   └── terrain_features.py
│
├── ingestion/
│   ├── rainfall.py
│   ├── forecast.py
│   ├── soil.py                      # bulk-fetched, not per-coordinate (Section 7.3)
│   ├── iot.py                       # simulated (Section 18.3)
│   └── fallback.py                  # per-layer fallback chain (Section 14.4)
│
├── alerts/
│   ├── cap.py
│   ├── sachet.py
│   ├── sms.py
│   └── authorization.py             # two-person gate (Section 12.4)
│
├── frontend/
│   ├── map/                         # MapLibre GL + deck.gl H3HexagonLayer (Section 15.4)
│   ├── dashboard/
│   ├── alerts/
│   └── validation/                  # LOEO/LORO panel (Section 17.9)
│
├── data/
│   ├── static/
│   ├── historical/                  # pooled, subfoldered per region for LORO folds
│   ├── shelters/
│   └── cached_demo/                 # 5–10 shortlist locations (Section 14.3)
│
└── docs/
    ├── architecture.md
    ├── data_dictionary.md
    ├── validation.md
    └── limitations.md
```

### 20.5 Appendix B — Implementation checklist

Adapted from v5's Appendix B: every item assuming a manually-configured region is replaced with an item testing the onboarding pipeline against an arbitrary location. Section 14.8 already has the demo-day operational checklist in full — this list does not repeat it, only cross-references it.

- [ ] Autonomous Region Onboarding Pipeline resolves a boundary for an arbitrary typed place name, with no hardcoded region in any module (Section 6)
- [ ] SoilGrids bulk raster pre-fetched via WCS/GEE for the demo shortlist before any live demo (Section 16.2)
- [ ] Geotechnical parameters derived via pedotransfer correlation, not a lookup table keyed by lithology class (Section 9.2 — the lookup table no longer exists)
- [ ] H3 grid resolution chosen automatically from the resolved boundary's extent, not a config value (Section 14.7)
- [ ] Static features generated for a genuinely novel, non-shortlist location, not only the shortlist (Section 14.3)
- [ ] Dynamic rainfall and soil-saturation features update on the scheduled refresh cycle (Section 14.6)
- [ ] FS is calculated, with uncertainty band width and correct shared `cos²β` exponent in both the FS and pore-pressure terms (Section 9)
- [ ] FS uncertainty band widens automatically when `has_local_calibration` is false (Section 9.2, Section 11)
- [ ] `hand_m`, `flow_accumulation`, `curve_number` included in the static feature table, not just computed for visualization (Section 10.3)
- [ ] Historical events loaded as a pooled, multi-region set, not a single-region inventory (Section 10.4)
- [ ] Event-centered temporal samples generated, holding every timestep of an event together (Section 10.5)
- [ ] XGBoost trains on the full 29-feature pooled table (Section 10.3)
- [ ] LOEO validation runs and is frozen (Section 17.2, Section 17.9)
- [ ] LORO validation runs and is reported **per held-out region**, not only as one pooled figure (Section 17.3)
- [ ] Spatial block validation runs (Section 17.5)
- [ ] Metrics reported per hazard type, flood vs. landslide, not combined only (Section 17.4)
- [ ] Model performance reported with and without `gsi_susceptibility_class`, to check circularity (Section 17.6)
- [ ] Confidence-score check: LORO-held-out regions show systematically lower confidence than calibrated regions at similar risk levels (Section 17.8)
- [ ] Risk score, tier, and three-factor confidence breakdown generated and correctly labelled — an engineered index, not a calibrated probability (Section 11)
- [ ] Forecast-based time-to-RED generated, not presented as a precise countdown (Section 18.5)
- [ ] Dashboard displays H3 risk with per-layer source/quality badges, live vs. cached visibly distinguishable (Section 13, Section 14.4)
- [ ] Feature-contribution panel displays (Section 10.7)
- [ ] Simulated IoT and simulated GSI/SAsiaFFGS signals labelled as simulated everywhere they appear (Section 18.3)
- [ ] Sensor fallback demonstrated live, mid-demo, not only described (Section 14.5)
- [ ] Orange/Red triggers a drafted CAP object held for two-person authorization, not auto-published (Section 12.4)
- [ ] Shelter lookup works
- [ ] Cached fallback is visibly labelled whenever it triggers, per layer (Section 14.4)
- [ ] Validation results (LOEO, LORO per-region, spatial-block) are shown on the dashboard, not only in this document (Section 17.9)
- [ ] No illustrative value is ever presented as measured model output
- [ ] Full Section 14.8 pre-demo checklist passes, including a genuinely novel non-shortlist location tested live

### 20.6 Appendix C — Design rationale FAQ

**Are you replacing SAsiaFFGS?**
No. HydraSense is a last-mile downscaling layer (Section 3).

**Are you replacing GSI?**
No. GSI remains the upstream landslide-guidance reference; where GSI-mapped data exists, it improves confidence rather than being superseded (Section 4, Section 6).

**Why XGBoost?**
Practical for heterogeneous tabular data and the modest pooled event counts realistically obtainable, while still providing feature-importance explainability (Section 10.2).

**Why not deep learning?**
The pooled event count (Section 10.4) — not a single pilot region's count, but the total obtainable across all regions — is not yet large enough to justify a deep temporal model as the primary approach. LSTM/GRU remains a Phase 3 upgrade path once that changes (Section 10.8, Section 19.4).

**Why use physics?**
The Factor-of-Safety layer provides physically interpretable slope-stability information and an uncertainty band that the ML fusion layer consumes rather than replaces (Section 9, Section 10.1).

**How do you know the model works?**
Leave-One-Event-Out validation for event-level generalization, and — because this project claims to be region-agnostic — Leave-One-Region-Out validation, reported per region, as the test that actually speaks to that specific claim (Section 17).

**How do you calculate lead time?**
Project forecast rainfall forward, recompute dynamic features, rerun the trained model, and identify the earliest RED crossing (Section 11).

**Is the lead time guaranteed?**
No. It is a model- and forecast-derived estimate, itself uncertain because the forecast input degrades with lead time (Section 18.5), and must be evaluated against historical events (Section 17.2) rather than trusted as a fixed countdown.

**Is HydraSense really a national system, or is it just wherever you happened to test it?**
Architecturally, yes, it is national: the Autonomous Region Onboarding Pipeline (Section 6) resolves terrain, land cover, and geotechnical parameters for any hilly location from globally-queryable sources, with no manual per-region setup step. What is **not** claimed is empirical validation across every hill state — that would require far more regional event data than a hackathon timeline allows, and GSI itself, with a national mandate, targets full coverage only by 2030 (Section 4). LORO results (Section 17.3) should be read as evidence of the degree of cross-region transfer actually achieved, not as proof of universal accuracy — this is the precise distinction Section 1 and Section 7.1 insist on.

**What's the actual difference between "architecturally region-agnostic" and "works everywhere"?**
The pipeline runs identically for any queried location with no manual setup — that part is true today and demonstrable live (Section 6, Section 14.2). Whether the *output* is equally trustworthy everywhere depends on whether that location has local historical event data to calibrate against, and most of hilly India currently doesn't (Section 4, Section 18.9). The system is built to say so out loud, per region, via the third confidence factor (Section 11, Section 17.8) — rather than silently presenting a data-rich region and a data-sparse one as equally certain.

**Isn't SoilGrids being down a fatal flaw?**
It's a real, verified current limitation (Section 7.3), not a hidden one — and the mitigation is itself part of the demo's design rather than a workaround to apologize for: geotechnical rasters are bulk pre-fetched via WCS/GEE ahead of time (Section 16.2), and for a genuinely novel location outside that pre-fetch, the system says plainly that it's running a terrain-only estimate with reduced confidence rather than faking a soil value (Section 14.2, step 3). Section 7.3 already frames this as a demo strength — visibly showing a real fallback path — rather than something to disguise.

**Is the GSI signal real-time?**
Not in this phase, unless an authorized operational integration exists. The prototype uses a clearly labelled simulated GSI-equivalent signal (Section 18.3).

**Does "hyper-local" mean every data layer is hyper-local?**
No, and the document says so plainly rather than implying it. DEM is ~30m, land cover 10m, SoilGrids-derived soil parameters 250m — genuinely fine-grained. ERA5-Land and SMAP, the regional dynamic layer, are ~9–11km — one rainfall/soil-saturation value can cover an H3 resolution-8 hexagon many times over (a hex averages ~0.737 km², roughly 800–920m across — Section 8.6's corrected figure). Hyper-locality in this system comes from fusing a coarser regional hazard signal with fine-grained local terrain susceptibility, not from every input being locally precise (Section 8.1).

**Is the confidence score a real probability?**
No. It's an engineered index combining three factors — model-probability skew, FS-uncertainty width, and whether local historical calibration exists (`has_local_calibration`) — with no formal statistical derivation (Section 11). It should be presented as "a combined uncertainty and calibration indicator," not a calibrated probability of correctness.

**Why did the pore-pressure formula use `cos²β` instead of `cos β`?**
Both the FS equation's normal-stress term and the pore-pressure term derive from the same normal-stress decomposition and must share the same exponent; an earlier working version used a single power of `cos β` for pore pressure, which was inconsistent with the `cos²β` already present in the FS numerator. This has been corrected throughout (Section 9).

**Do you calculate evacuation routes?**
Not in this phase. The shelter component is a static lookup; dynamic routing is roadmap functionality (Section 18.8, Section 19.3).

**Do you model population exposure?**
Not in this phase. Exposure-weighted risk (`Hazard × Exposure × Vulnerability`) is a Phase 2 extension using WorldPop/OpenStreetMap (Section 18.8, Section 19.3).

**Why not just hardcode one well-studied pilot region — wouldn't that be more accurate?**
It would very likely show a higher headline accuracy number, and that's exactly why it was rejected (Section 6, decision #1). A single-region system with a manual config layer proves the model can fit one place well; it proves nothing about whether the architecture generalizes, which is the actual problem statement (Section 2). The honest trade this document makes instead: architectural region-agnosticism that's real and demonstrable today, paired with a validation strategy (LORO, Section 17.3) and a confidence mechanism (Section 11) that say plainly where empirical accuracy is and isn't yet backed by data — rather than a higher number earned by only ever being tested where it already works.

**What is your strongest contribution?**
The combination of last-mile spatial downscaling, physics + ML fusion, a genuinely region-agnostic onboarding pipeline with zero manual per-region setup, and a validation and confidence design that states honestly — per region, at prediction time — how much of that region-agnostic claim is architecture versus how much is yet-unproven empirical accuracy.

### 20.7 What this section deliberately does not claim

Appendix B's checklist is a hackathon-completeness list, not a production-readiness audit — that would require the real institutional integrations, real sensor deployment, and continuous validation Section 19.6 (Phase 5) describes, none of which this checklist assumes. Appendix C does not claim to anticipate every question a judge could ask — it prioritizes the questions most likely to probe this document's two most novel and most easily-misunderstood claims: the region-agnostic/empirical-accuracy distinction (Section 1, Section 7.1) and the SoilGrids workaround (Section 7.3). And Appendix A's folder structure is a reasonable organizational default, not an architectural requirement this document takes a position on the way it does for the datastore or map-rendering choices in Section 15.

---

*Document status: all 20 sections drafted. Sections 8.6 and 9 record two corrections made to earlier sections during drafting — the H3 resolution-8 area figure and the pore-pressure exponent — left visible rather than silently fixed, consistent with the honesty principle this document asks of its own risk output.*
