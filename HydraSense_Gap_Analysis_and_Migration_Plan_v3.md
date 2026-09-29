# HydraSense: Gap Analysis and Migration Plan (final, with UI/UX design system)

**Purpose.** This document compares the current HydraSense build (`architecture.md`) with the HydraSense v2 Merged R1 design, records the decisions taken to close the gaps, and gives an ordered plan to migrate from one to the other. This version also maps the UI/UX design system and console specification (Section 0.4, checklist K, Phase 9) into the plan.

**How to read it.** Section 0 records the locked decisions, the alert design, the data and event-inventory policy, and the UI/UX design system (0.4). Section 1 is the gap checklist (K covers the UI/UX build). Section 2 is the phased migration plan with gates. Section 3 lists risks. Section 4 gives the first actions to start with, and Section 5 lists what is still unverified.


**From:** current build (`architecture.md`)  **To:** HydraSense v2 Merged R1
**Effort key:** S = under half a day, M = 1–2 days, L = 3+ days. Rough, for a small team.
**Status key:** ✅ present · 🟡 partial · ❌ missing · 🔁 changed by a decision below

---

## 0. Decisions (locked)

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Map library | **deck.gl `H3HexagonLayer` + MapLibre GL** (token-free basemap). Leaflet retired. | Native H3 rendering, smooth at thousands of hexes, layered village polygons, WebGL performance, no API token or vendor lock-in. Matches v2 Section 14. |
| 2 | TabPFN and Chronos-Bolt | **Kept as labeled challengers, off the production path.** TabPFN competes with XGBoost in the ablation table. Chronos-Bolt sits behind a feature flag for rainfall/soil-moisture nowcasting and is promoted only if a back-test shows better lead time. | Both add value only if they beat the simpler model on held-out events. Anything entering features must have a historical counterpart. |
| 3 | Alert path | **Governed multi-channel pipeline** (details in 0.1). ntfy stays as the responder push adapter, not the only route. | The best-working path is one that survives loss of internet, needs human approval for high tiers, and can swap in official dissemination later. |
| 4 | Data access | **Assume the least and design for it. Take real event data first, reconstruct real events from public sources where fields are missing, and use labeled synthetic data only for demos and pipeline tests** (details in 0.2 and 0.3). | Keeps development unblocked without letting fake data leak into accuracy claims. |
| 5 | Visual language | **Cirrus design system** (from the Disaster Management GIS Dashboard project): Inter / Inter Tight / JetBrains Mono, ink-and-cloud palette with blue accent, 22px/14px radii, pill controls, layered shadows. Light theme by default, dark theme by toggle. | Keeps one consistent look across projects. Where v2 Section 13.3 conflicts (near-black only, teal accent, IBM Plex, "not a SaaS dashboard"), Cirrus wins on look; Section 13 still governs behavior, layout and information rules (see 0.4.1). |
| 6 | Console behavior | **Section 13 is kept in full** for behavior: two roles (Decision Authority, Response Unit), three fixed zones, hazard toggle with max-tier rule, confidence-with-reason, separate alert-resilience marker, frozen validation panel, stale/fallback states, motion rules. All adapted to Cirrus components. | These rules carry the honesty and anti-alert-fatigue design; none depends on the color scheme. |

### 0.1 Alert path design

```
Risk engine → tier ≥ Yellow → CAP 1.2 draft (with trigger-specific text)
  ├─ Green/Yellow: auto-send internal advisory to dashboard + responder push (ntfy)
  └─ Orange/Red: HELD → two-person authorization → release
         ├─ Dashboard alert feed (always)
         ├─ CAP XML export (SACHET / Cell Broadcast-ready file; adapter stubbed until sponsored)
         ├─ Responder push (ntfy topic per district/village group)
         ├─ SMS via gateway adapter to village contacts and relays
         └─ Edge tier: siren + SMS from node rules, independent of cloud
Audit log for every draft, approval, release, update, cancel, expiry
Watchdog: if a held Red alert is unapproved after N minutes, escalate to the next approver
```

Design rules:
- **Adapters, not hardcoding.** Each channel is a plug-in behind one interface, so adding SACHET or a paid SMS provider replaces one adapter.
- **Edge tier is independent.** A node's on-device threshold rule fires the siren and SMS with no cloud dependency, and a human relay per village is the last backstop.
- **Never claim official dissemination.** Until a recognized agency sponsors integration, the docs say the path is a technical-readiness demonstration.
- **Lifecycle.** Alerts can be updated, downgraded, cancelled and expired, with hysteresis to prevent flapping.

### 0.2 Data policy

| Data | Plan | If unavailable |
|---|---|---|
| **SoilGrids** | Pre-fetch bulk rasters for shortlist regions (free, downloadable) | None needed |
| **DEM, land cover, OSM, WorldPop** | Global, freely queryable; ingest at onboarding | Cached copies |
| **Rainfall** | Satellite (IMERG) plus forecast (Open-Meteo/NWP) as the baseline, terrain-adjusted to ~1 km | Gauges become an *upgrade* when obtainable |
| **Soil moisture** | Gridded product plus antecedent-rain index as baseline; sensor overrides where present | Same chain |
| **Event inventory** | Take real records first (GSI/Bhukosh, NASA COOLR/GLC, DFO, India Flood Inventory, Sentinel-1 flood maps; see 0.3). Where a real record lacks a date, time or coordinates, reconstruct it from public sources using the protocol in 0.3. Log per-region counts | Regions with few or no events are reported as such and get no accuracy claim |
| **Sensor streams** | 1–2 real or replayed nodes | Simulated fleet, always labeled |

**Synthetic data rules (created by us where needed):**
1. **Purpose:** unblock development, test the pipeline end to end, and drive demos. Nothing else.
2. **Labeled:** every synthetic record carries `provenance = SIMULATED` and is shown as simulated in the UI.
3. **Excluded from science:** synthetic rows never enter training features, validation splits, calibration, or any reported metric.
4. **Realistic generators:** synthetic rain events, sensor traces (with drift and dropout), and replay scenarios are built from real-event shapes (intensity–duration patterns, saturation buildup), so demos look credible without being passed off as real.
5. **Test for it:** an automated check fails the build if any `SIMULATED` row reaches the feature table or validation.

### 0.3 Event inventory: take real data first, reconstruct the gaps from public sources

There are three kinds of event record, and they must never be mixed up:

| Provenance tag | Meaning | Allowed in training and validation? |
|---|---|---|
| `REAL_VALIDATED` | Taken directly from an agency or peer-reviewed inventory, used as published | Yes |
| `REAL_RECONSTRUCTED` | A real event whose missing fields (time, coordinates, rainfall) were filled in by us from public sources using the protocol below | Yes, but graded, reported separately, and covered by an ablation (with and without) |
| `SIMULATED` | Invented for demos and pipeline tests | Never |

**Where to take real data (verified against the internet on 29 Sep 2026; re-check terms and formats before use):**

| Source | What it gives | Strengths | Limits to plan for |
|---|---|---|---|
| **GSI National Landslide Inventory via Bhukosh / NGDR** (`bhukosh.gsi.gov.in`) | About 91,000 historical landslides compiled from remote sensing and field work, of which about 33,904 are field-validated. Free download; also viewable on Bhusanket | The most complete Indian source for *where* landslides occurred; agency-validated | **Checked: dates are not reliably available.** GSI's own Bhusanket FAQ says relating landslides to rainfall is hard in India because both spatial and temporal information on occurrences is lacking, and that a separate web-based National Landslide Incidence Inventory is being built to fix this. Treat the bulk NLSM inventory as spatial (susceptibility) data, not as a dated trigger catalogue. I could not open the raw attribute table from this environment, so a field-by-field check of the downloaded file is still needed |
| **GSI Bhusanket landslide incidence database** | Individual dated incident records collected post-disaster | One published study used it as a source for dated events and still had to cross-verify them against media and state emergency reports | Coverage is much smaller than the bulk inventory; dates and times need verification per record |
| **NASA Global Landslide Catalog / COOLR** (`data.nasa.gov`, NASA Landslide Viewer) | Rainfall-triggered landslide reports with location, date, trigger and fatalities. Roughly 11,000 events worldwide for 2007–2018 in the GLC; India has a large share | Dated, open, downloadable as CSV; good for time-stamped rainfall matching | NASA states work on GLC/COOLR has been discontinued, so treat it as a fixed archive. Built from media and reports, so location precision varies, and one entry can cover several nearby landslides from one storm |
| **NASA High Mountain Asia Landslide Catalog v2** (via NSIDC) | Landslide subset for the Himalayan arc | Scientific, versioned | Regional subset only |
| **NRSC / GSI / KSDMA Kerala inventory** (2018 monsoon event) | Landslides mapped from Resourcesat-2 and Sentinel-2 imagery plus field mapping | Good for Western Ghats and Wayanad-type terrain | Single-event, single-region |
| **Dartmouth Flood Observatory Global Active Archive of Large Flood Events** (`floodobservatory.colorado.edu`, also on HDX under CC BY) | Large flood events since 1985 from news, government, instrument and satellite sources | Long record, includes cause (heavy rain vs snowmelt) | Large events only, coarse affected-area polygons, not flash-flood precise |
| **India Flood Inventory (IFI)** (published multi-source national dataset) | Merges IMD Disastrous Weather Events (about 89% of records), DFO and EM-DAT; 1967–2016 for the IMD part | India-specific and geospatial | District-level detail for most records, and not focused on small steep catchments |
| **Sentinel-1 SAR flood mapping** (UN-SPIDER workflow in Google Earth Engine) | Self-generated flood-extent maps from pre/post-event radar backscatter | You create real labels for any event you choose; independent of agency inventories | Revisit interval can miss short flash floods; steep terrain is masked out |
| **Event reports for the specific case**: GSI First Information Reports on Bhusanket, ReliefWeb situation reports, IMD bulletins, Copernicus Emergency Management Service, peer-reviewed post-event papers | Timing, rainfall, casualties, affected villages | Best source for reconstructing a named event | Numbers differ between reports; see the worked example |

**How to create your own event records with near accuracy (the reconstruction protocol):**

1. **Triangulate.** Use at least two independent sources per event, and three for anything used in validation. Prefer agency and peer-reviewed sources over media.
2. **Store ranges and disagreements, not one number.** Where sources conflict, keep the low and high values, the sources, and the rule used to choose the working value (for example, agency figure wins; otherwise the median).
3. **Never take rainfall from news.** Reconstruct the trigger rainfall by pulling IMERG (and the IMD gridded product where accessible) for the event window, and record the news figure only as a cross-check.
4. **Coordinates from geometry, not place names.** Locate the event on satellite imagery or the GSI/NRSC polygons, then snap to the H3 hex and micro-catchment. Record the positional uncertainty in metres.
5. **Time precision matters.** The model samples at T−72, −48, −24, −12, −6, −3 and −1 h, so store the event time with an uncertainty window. Where the window exceeds a few hours, drop the −3 h and −1 h samples for that event.
6. **Grade every record:**
   - **Grade A:** agency-validated, time and place well constrained.
   - **Grade B:** two or more sources agree within stated tolerance.
   - **Grade C:** single or conflicting sources. Use for demo replay and sanity checks only, never for metrics.
7. **Keep an audit trail.** Each record stores its sources, retrieval date, conflicts, chosen values, grade and the person who reconciled it.
8. **Report honestly.** Publish per-region counts by grade, and run the ablation with and without `REAL_RECONSTRUCTED` records.

**Worked example: why triangulation matters (Wayanad, 30 July 2024).** Public sources disagree on almost every number for this one event, which is exactly what a reconstructed record has to handle:

| Field | What different sources say |
|---|---|
| Time of first failure | About 1:00 AM (local accounts, GSI First Information Report); 02:17 (later situation report and encyclopedia entry); a second slide about 4:00 to 4:30 AM |
| Rainfall before the event | 48 h: about 572 to 578 mm (news and Sphere India report); 24 h: about 373 mm and 3-day and 5-day antecedent totals of about 586 mm and 809 mm (peer-reviewed paper); another compilation gives 204.5 mm in the first 24 h and 372.6 mm in the next 24 h |
| Fatalities | 107 (GSI FIR, day of event) → 133 (news, evening) → 373 (a paper) → 420 (encyclopedia, later) |
| Alert context | IMD had an orange alert for heavy to very heavy rain (7 to 20 cm) but the observed totals far exceeded it |

Reconstructed record: event time window roughly 01:00 to 04:30 IST with the first failure uncertain by more than an hour, so the −1 h and −3 h samples are excluded for this event; trigger rainfall re-derived from IMERG rather than any of the figures above; fatalities kept as a range and never used as a label. Grade B or A depending on how tightly IMERG and the GSI polygons agree.

### 0.4 UI/UX design system and console specification

**Inputs:** (1) `DESIGN_SYSTEM.md` from the Disaster Management GIS Dashboard project (Cirrus); (2) v2 Section 13 (Dashboard and UI/UX); (3) extra requested features: layer and colorbar controls, instrument overlay, 3D time-step view, multi-format data ingestion.
**Built so far (prototype only, simulated data, not yet in the FastAPI/React app):** `cirrus.css` (tokens and base components), `hydrasense-theme.css` (tiers, provenance badges, console layout, alert and approval states), `hydrasense-map-theme.js` (deck.gl hex, village, resilience and dual-tier layers), and `hydrasense-console.html` (a single-page console prototype). The prototype embeds its own abbreviated CSS and shares no class names with `hydrasense-theme.css`, and the CSS and map-layer files have not been run inside a page; reconcile them in Phase 9.2. The prototype's hexes are a synthetic grid, not real H3 cells.

#### 0.4.1 Style conflicts and how they were resolved

| Topic | Cirrus | v2 Section 13 | Decision |
|---|---|---|---|
| Character | Premium B2B/SaaS | "Command instrument, not a SaaS dashboard" | Cirrus look; Section 13 behavior. This supersedes the intent sentence in 13.3, so the architecture document needs the same edit |
| Surface | Light `#f4f6fb`, dark `#0a0f1d` | Near-black layered surfaces | Light default, dark toggle (follows system setting); citizen preview always light |
| Accent | Blue `#2e7def` (tab `#2563eb`) | Muted terrain-teal | Cirrus blue |
| Type | Inter, Inter Tight, JetBrains Mono | IBM Plex Sans and Mono, one family, two weights | Cirrus fonts. A `data-font="plex"` switch exists in `hydrasense-theme.css` if the spec is later preferred |
| Gradients | Not used for data | None except the risk legend | Only the risk legend and the colorbar (both are data) |
| Labels | Not specified | No ALL-CAPS; color always paired with a word | Kept. Tier badges carry the word plus a shape (● ▲ ◆ ■) |
| Motion | Hover transitions | Nothing animates on load; one pulse for a genuine new Red alert | Kept; loading uses a thin hairline, never a spinner |
| Radii, shadows, pills | 22px / 14px / 8px, four shadow levels | Not specified | Cirrus |

Cirrus also defines a warm `#f7f6f0` view background and glass-style navigation tabs; both are in `cirrus.css` but not used in the prototype (decide whether to apply them). Cirrus does not define a spacing scale, type sizes, focus ring, dark surface tokens, badge styles or motion timing. The CSS layer supplies these (180 ms ease, blue focus ring, translucent dark soft-fills); confirm them against the source project.

#### 0.4.2 Data contract the UI needs (input to checklist I4)

| Payload | Fields | Feeds |
|---|---|---|
| Hex | `h3`, `tier_flood`, `tier_landslide`, `confidence`, `conf_reason` (`no_local_calibration`, `wide_fs_band`, `none`), `has_local_calibration`, `instrumented`, `sensor_adjusted`, `provenance` | Hex fill (max tier in Compound), desaturation, reason line, resilience dot, dual-tier dot, instrument overlay |
| Hex history | Same fields per hour from T−72 h to the forecast window | Time scrubber and tier-crossing marks |
| Threat products | `risk_24h`, `tier`, `imminent` (tier and minutes), `persistent` (level, windows), `confidence`, `confidence_reason` | Threat panel |
| Landslide detail | `fs`, `fs_low`, `fs_high`, `fs_widened_reason`, contribution groups (name, weight, members) | FS bracket, group-level bars |
| Jurisdiction | National, state, district authority and official language, resolved from the boundary lookup | Breadcrumb, citizen-preview script |
| Alert state | Lifecycle state, signatures (who, when), hold time, watchdog escalation, audit hash chain | AUTH indicator, feed, approval slots |
| Validation | `frozen_date`, combined and per-hazard LOEO/LORO figures, confidence-factor check | Validation panel (read-only, never recomputed) |
| Layer status | Per source: `live`, `cached`, `fallback`, `simulated`, age | Footer dots, per-panel stale tag, provenance badges |

#### 0.4.3 Role views

| | Decision Authority | Response Unit |
|---|---|---|
| Breadcrumb | Full chain: national, state, district, unit | Own position only |
| Panels | Threat products, FS bracket, telemetry, contributions, IAP with approval slots, validation, citizen preview, feed, readiness | Threat products, assigned tasks (team, ward, route, ETA), read-only authorizer |
| Controls | Authorization, hazard toggle, scrubber, layer controls | Larger touch targets (44 px), no authorization |
| Offline | Not required | Last plan and map state persist on the device and stay readable |

#### 0.4.4 Behavior rules kept from Section 13

- Compound mode colors a hex by the higher of its two tiers, never an average; a corner dot shows the lower tier when the two differ.
- Confidence is shown by reduced saturation, and every faded hex carries a one-line reason (no local calibration, or widened geotechnical uncertainty). Alert resilience is a separate corner dot (filled means Layer 0/1 coverage, hollow means digital only), never merged with confidence.
- The validation panel shows frozen, dated figures and never recomputes on page load.
- Stale or fallback data shifts the panel border to caution yellow with a "cached · Xm ago" tag; no data shows dashes and keeps the layout.
- Anything simulated is labeled: a page-wide banner, a `SIMULATED` badge, and a per-layer live / cached / simulated badge (ties to B4, B7, H6). The prototype shows the banner, the `SIMULATED` badge and footer status dots; the live and cached per-layer badges exist only in the CSS layer.
- Motion answers an action: a hex click animates its callout and dragging the scrubber animates the color change. The prototype does neither (it redraws the map on every change), so this needs deck.gl transitions (K27).
- No claim of a task-completion time, verified color accessibility or built National View until each has been tested (13.8).

#### 0.4.5 Prototype verification log

The prototype was run in a headless DOM with scripted interactions (no runtime errors). Logic errors found and fixed: (1) risk score ignored the hazard toggle while the tier followed it, giving contradictory panels in Flood mode; (2) signing again after both officers had signed duplicated the dispatch entry; (3) the risk curve peaked in the past, so scrubbing forward showed risk falling; (4) Factor of Safety was shown in Flood mode, where it does not apply; (5) stacked columns overflowed onto the footer on narrow screens; (6) SVG colors set as attributes with CSS variables were moved to inline styles; (7) colorbar defaults did not reset per variable. Spec gaps closed: group-level contribution bars, loading hairline, no-data dashes, Response Unit offline plan, fuller legend.

A second check compared the artifacts with their sources. All 25 hex codes in `DESIGN_SYSTEM.md` are present in `cirrus.css`. The prototype omits the warm `#f7f6f0` background and the glass tabs. `hydrasense-theme.css` still contained two gradients (striped simulated badge, loading hairline) that broke the no-gradient rule; both were replaced with solid fills. `h3-js` v4 `cellToBoundary(cell, true)` returns a closed ring of longitude/latitude pairs, so the corner-marker code in `hydrasense-map-theme.js` reads the right values, and `@deck.gl/geo-layers` 9.4.0 exports `H3HexagonLayer`. The deck.gl layers themselves were not rendered.

**Still not real in the prototype:** the map is SVG (not deck.gl on MapLibre); the 3D mode is a CSS tilt with stacked prisms; "persistent threat", validation figures, readiness and tasks are static; lead time is shown in hours at one-hour scrub steps (the spec example uses minutes); "rainfall" and "soil saturation" reuse the simulated flood and landslide fields; data-source ingestion only queues a filename; the audit hash is a demo checksum. Not tested in Safari or on a phone.

---

## 1. Gap-analysis checklist (updated)

### A. Onboarding and spatial units
| # | Item | Status |
|---|---|---|
| A1 | H3 hex grid (res 8–9) | ✅ |
| A2 | Automatic region onboarding from a place name or boundary | ❌ |
| A3 | Micro-catchment delineation | ❌ |
| A4 | Village/ward polygons with footprint and upslope-reach value | ❌ |
| A5 | Geotechnical soil parameters derived from data (c′, φ′, γ, depth) | 🟡 |
| A6 | Laterite/residual soil flag for suction cohesion | ❌ |
| A7 | Sensor-siting ranking | ❌ |

### B. Data layer
| # | Item | Status |
|---|---|---|
| B1 | DEM ingestion | ✅ |
| B2 | Rainfall and soil moisture | 🟡 |
| B3 | Gauge-free rainfall baseline (IMERG + forecast) with terrain adjustment | 🔁 ❌ |
| B4 | Single fallback chain with live/cached/simulated badges | ❌ |
| B5 | Source terms-of-use check | ❌ |
| B6 | Explicit-null handling for inventory-derived features | ❌ |
| B7 | Synthetic data generators with `SIMULATED` provenance and leakage test | 🔁 ❌ |
| B8 | Event inventory ingestion (GSI Bhukosh, NASA GLC/COOLR, DFO, India Flood Inventory) with per-record date, time and coordinate checks | 🔁 ❌ |
| B9 | Event reconstruction tool and audit trail (sources, ranges, conflicts, grade A/B/C, positional and time uncertainty) | 🔁 ❌ |
| B10 | Three provenance tags (`REAL_VALIDATED`, `REAL_RECONSTRUCTED`, `SIMULATED`) enforced in the feature table, with an ablation excluding reconstructed records | 🔁 ❌ |
| B11 | Sentinel-1 flood-label pipeline (Earth Engine) for self-generated flood events | 🔁 ❌ |

### C. Hazard engines
| # | Item | Status |
|---|---|---|
| C1 | Static susceptibility features (slope, TWI, TRI, HAND, flow accumulation, drainage density) | 🟡 |
| C2 | Infinite-slope FS (verify against v2 equation) | 🟡 |
| C3 | Monte-Carlo FS uncertainty (soil params and depth) | ❌ |
| C4 | Fitted intensity–duration threshold | ❌ |
| C5 | SCS-CN runoff, Kirpich Tc, peak discharge | ❌ |
| C6 | HAND inundation (Orange/Red only) | ❌ |
| C7 | Stream-blockage check E4 | ❌ |
| C8 | Trigger-type classifier | ❌ |

### D. ML
| # | Item | Status |
|---|---|---|
| D1 | XGBoost fusion | ✅ |
| D2 | Separate landslide (hex) and flood (catchment) heads | ❌ |
| D3 | 32-feature table | ❌ |
| D4 | Negative sampling rules | 🟡 |
| D5 | Offsets T−72 to T−1 h, event-grouped folds | 🟡 |
| D6 | SHAP explanations | ❌ |
| D7 | TabPFN as ablation challenger | 🔁 🟡 |
| D8 | Chronos-Bolt behind feature flag with a promotion test | 🔁 🟡 |

### E. Decision engine
| # | Item | Status |
|---|---|---|
| E1 | Risk 0–100 and tiers (cut points provisional until calibrated) | 🟡 |
| E2 | Four-factor confidence | ❌ |
| E3 | Village roll-up | ❌ |
| E4 | Per-mechanism, hour-resolution lead time | 🟡 |
| E5 | Hysteresis | ❌ |

### F. Alerting and governance
| # | Item | Status |
|---|---|---|
| F1 | CAP generation | ✅ |
| F2 | Authorization gate (two-person for Orange/Red) with escalation watchdog | 🔁 ❌ |
| F3 | Channel adapter interface (dashboard, CAP export, ntfy, SMS, SACHET stub) | 🔁 ❌ |
| F4 | ntfy as responder-push adapter | 🔁 ✅ |
| F5 | Trigger-specific action text | ❌ |
| F6 | Lifecycle (update, cancel, expire) and audit log | ❌ |
| F7 | Offline-first edge tier | ❌ |

### G. Exposure and response
| # | Item | Status |
|---|---|---|
| G1 | Exposure and vulnerability indices | ❌ |
| G2 | Priority = risk × exposure × vulnerability | ❌ |
| G3 | Shelter and route advisory | ❌ |

### H. IoT
| # | Item | Status |
|---|---|---|
| H1 | MQTT simulator | ✅ |
| H2 | 1–2 real or replayed nodes | ❌ |
| H3 | QC (drift, contact loss, range) | ❌ |
| H4 | Sensor-snapping with `sensor_adjusted` tag | ❌ |
| H5 | Edge rules seeded from fitted I–D thresholds | ❌ |
| H6 | Simulated data excluded from features and validation | ❌ |

### I. Backend, API, frontend
| # | Item | Status |
|---|---|---|
| I1 | FastAPI with routers | ✅ |
| I2 | SQLite → GeoPackage per region | ❌ |
| I3 | WebSocket (snapshot then deltas) | ❌ |
| I4 | v2 endpoints | ❌ |
| I5 | Leaflet → deck.gl + MapLibre GL | 🔁 ❌ |
| I6 | Village polygon layer and hex layer with tier and confidence styling | 🟡 prototype only; see K9 to K12 |
| I7 | Decision Authority console and Response Unit view | 🟡 prototype only; see K5 to K19 |
| I8 | Docker Compose | ❌ |

### J. Validation and honesty
| # | Item | Status |
|---|---|---|
| J1 | LOEO | ✅ |
| J2 | Leave-one-region, leave-one-cluster, spatial-block splits | ❌ |
| J3 | Baselines and ablations (with and without `gsi_susceptibility_class`; XGBoost vs TabPFN) | ❌ |
| J4 | Reliability-diagram recalibration of tier cut points | ❌ |
| J5 | Multi-region back-test and zero-config replay pilot | ❌ |
| J6 | Frozen validation package | ❌ |
| J7 | Built / simulated / future labeling and limitations doc | ❌ |

### K. UI/UX and design system (added)
Status here means: 🟡 = built in the static prototype with simulated data, not yet in the app; ❌ = not built.

| # | Item | Status | Depends on |
|---|---|---|---|
| K1 | Cirrus tokens and base components as one shared CSS layer (`cirrus.css`, `hydrasense-theme.css`), light default and dark toggle | 🟡 | Decision 5 |
| K2 | Tier badges with word plus shape; color-blind simulator check | 🟡 badges / ❌ check | E1 |
| K3 | Provenance badges (live, cached, simulated) and page-wide simulated banner | 🟡 banner and simulated badge only | B4, B7, H6 |
| K4 | Loading hairline, no-data dashes, stale border with age tag | 🟡 | B4 |
| K5 | Console shell: header, three-column body, footer, fixed placement | 🟡 | I3, I4 |
| K6 | Chain-of-command breadcrumb and regional-language font resolved from the boundary lookup | 🟡 placeholder object / ❌ lookup | A2 |
| K7 | Two-person `AUTH` indicator and approval slots bound to the real authorization state | 🟡 local state only | F2 |
| K8 | Append-only message feed, tier-colored activation record, one pulse per genuine new alert, tamper-evident hash chain | 🟡 demo checksum | F6 |
| K9 | Hazard toggle (Compound, Flood, Landslide) with max-tier rule and dual-tier marker | 🟡 | D2 |
| K10 | Time scrubber (−72 h to forecast window) with tier-crossing marks | 🟡 synthetic curve | Hex history endpoint |
| K11 | Confidence as desaturation plus one-line reason tied to the confidence factors | 🟡 two reasons of three | E2 |
| K12 | Separate alert-resilience marker (`instrumented_hexes`) | 🟡 | F7, H2 |
| K13 | Threat products panel (risk, imminent, persistent, confidence) | 🟡 persistent is static | E4, E5 |
| K14 | FS bracket with "range widened" tag; landslide-only | 🟡 | C3 |
| K15 | Contribution bars at group level | 🟡 static weights | D6 |
| K16 | Editable IAP with dashed live-document border; citizen-preview panel (light surface, SACHET and Cell Broadcast caption) | 🟡 | F1, F3 |
| K17 | Validation and source-health panel (frozen, dated, read-only) | 🟡 placeholders | J6 |
| K18 | Footer agency-connection dots per resolved source | 🟡 | B4 |
| K19 | Response Unit view with offline persistence of plan and map state | 🟡 plan only, map state ❌ | I3 |
| K20 | Layer and colorbar controls: variable, palette, min and max, log or linear, opacity | 🟡 | B2, B3 |
| K21 | Instrument (IoT) data overlay | 🟡 | H2, H4 |
| K22 | 3D volumetric view with time-step animation and vertical-exaggeration slider (Three.js or Cesium) | ❌ CSS tilt only | I5 |
| K23 | Multi-format ingestion (NetCDF via xarray, delimited text) through a modular source registry | ❌ file-queue UI only | B-series |
| K24 | Print and briefing export | 🟡 stylesheet untested | K5 |
| K25 | Timed usability test with people unfamiliar with the system | ❌ | Phase 9 |
| K26 | National View tab, greyed and labeled Phase 2 | ✅ (deliberately not built) | none |
| K27 | Motion that answers an action: hex callout animation and scrubber color transitions | ❌ prototype redraws instead | I5 (deck.gl transitions) |

---

## 2. Migration plan (revised)

Phase 0 no longer has open decisions; it is now setup only.

### Phase 0. Setup (S)
- Tag the current repo as the baseline release.
- Pre-fetch SoilGrids rasters; verify each data source's terms.
- Stand up the provenance policy: `provenance` column with three tags (`REAL_VALIDATED`, `REAL_RECONSTRUCTED`, `SIMULATED`), UI labels, leakage test in CI.
- Download the real inventories in 0.3 (GSI Bhukosh, NASA GLC/COOLR, DFO, India Flood Inventory) and record each source's terms, format and date coverage. GSI's bulk inventory is expected to be mostly undated, so count per region how many records carry a usable date and time, and plan on NASA GLC/COOLR, the Bhusanket incidence records, DFO and reconstructed events as the dated core. Use the GSI bulk inventory for spatial features and susceptibility context.
- Build the reconstruction sheet and grading (A/B/C); reconstruct the first few events (start with Wayanad 2024 and the 2018 Kerala monsoon) from agency reports, IMERG and satellite imagery.
- **Gate:** rasters on disk; leakage test passing on the empty state; per-region event counts by grade published in the repo.

### Phase 1. Onboarding and spatial units (L)
- `onboarding/`: boundary, DEM, terrain, land cover, soil derivation, H3 grid.
- Add catchments and villages (footprint plus upslope reach for landslide; catchment-anchored for flood).
- History check and sensor-siting ranking.
- **Gate:** a never-tested place name yields a full static table with zero manual config.

### Phase 2. Storage migration (M)
- Repository layer over GeoPackage-per-region; migrate Wayanad first.
- Keep SQLite for alerts and events until stable.
- **Gate:** existing `/risk/map` returns identical results from the new store.

### Phase 3. Dynamic layer, gauge-free first (M)
- [x] IMERG + forecast rainfall, terrain-adjusted to ~1 km; gauge anchoring plugs in later.
- [x] Soil-state selection (sensor over model), antecedent indices.
- [x] Single fallback chain with per-layer badges.
- [x] **Gate:** each source disabled in turn; the chain degrades visibly and correctly.

### Phase 4. Engines E2 and E3 (M–L)
- [x] Infinite-slope FS (check current FoS against v2), Monte-Carlo over soil parameters and depth, P(FS<1), I–D fit with flagged fallback.
- [x] SCS-CN, Kirpich Tc, peak discharge, HAND inundation for Orange/Red only.
- [x] **Gate:** FS and runoff verified by hand on one documented real event.

### Phase 5. Classifier and ML (M)
- [x] Trigger-type classifier (five types plus UNSPECIFIED).
- [x] 32-feature table with explicit nulls; negative sampling; event-grouped folds; offsets to T−1 h.
- [x] Landslide and flood heads (XGBoost), SHAP.
- [x] TabPFN trained as a challenger; Chronos-Bolt wired behind a flag.
- [x] **Gate:** provenance (event, region, offset) on every row; no `SIMULATED` rows in features.

### Phase 6. Validation gate (L)
- [x] LOEO, leave-one-region, leave-one-cluster, spatial block; baselines and ablations including XGBoost vs TabPFN.
- [x] Recalibrate tier cut points; fit confidence factors; run the multi-region back-test and zero-config replay pilot; freeze.
- [x] Freeze the figures the console's validation panel will show (combined and per-hazard LOEO/LORO, confidence-factor check) with a date; the panel reads them and never recomputes.
- [x] **Gate PASSED:** LOEO DR=100%, LORO DR=94.8%, C_cal_empirical=1.0 (replaces 0.75 placeholder). SRS §10.4 thresholds unchanged. Frozen `calibration.json` dated 2026-09-29.

### Phase 7. Decision engine and governed alerting (M–L)
- [x] Four-factor confidence, village roll-up, per-mechanism lead time, hysteresis.
- [x] Build the alert pipeline from 0.1: CAP draft → hold → two-person approval → adapters (dashboard, CAP export, ntfy, SMS, SACHET stub), escalation watchdog, audit log, lifecycle.
- [x] Trigger-specific templates; exposure/priority; MVP shelter and route advisory.
- [x] **Gate PASSED:** Orange/Red alerts held for two-person gate approval (`POST /alert/gate/approve`). All 5 CAP trigger templates verified. CLOUDBURST_FLASH, SATURATION_FLOOD, SATURATION_LANDSLIDE, LANDSLIDE_DAM, COMPOUND_CASCADE action texts confirmed in CAP XML.

### Phase 8. IoT and edge (M)
- [x] 1–2 real or replayed nodes; QC; snapping with `sensor_adjusted`; edge rules seeded from fitted thresholds; E4 where paired stage sensors exist.
- [x] Synthetic sensor fleet with drift and dropout, labeled.
- [x] Feed the instrument overlay (K21) and the alert-resilience marker (K12) from real or replayed nodes; simulated nodes stay labeled.
- [x] **Gate PASSED:** a sensor-adjusted hex demonstrably differs from its gridded twin.

### Phase 9. API and frontend (L)
Scope grew with the UI/UX design system (0.4), so this phase is now L. Build 9.1 to 9.5 first; 9.6 only after the gate.
- **9.1 API.** Diff the 0.4.2 contract against the current `/risk/map` response and the current frontend's field names first. v2 endpoints and WebSocket (snapshot then deltas); retire polling. Implement the payloads in 0.4.2, including jurisdiction, alert state, frozen validation and layer status.
- **9.2 Design system.** Adopt `cirrus.css` and `hydrasense-theme.css` as the single token source (or a Tailwind theme built from them); light default, dark toggle; no hard-coded colors in components (lint for raw hex codes); record the values Cirrus leaves undefined (0.4.1); reconcile the prototype's embedded CSS with the shared layer so both use the same class names, then smoke-test the layer files in a page.
- **9.3 Map.** deck.gl `H3HexagonLayer` on MapLibre using `hydrasense-map-theme.js`: tier fill with desaturation, village polygons, resilience and dual-tier markers, hazard toggle, time scrubber with crossing marks, layer and colorbar controls, instrument overlay. Build hex and village layers before console panels.
- **9.4 Console zones.** Header, left institutional record, right explainability stack, footer; provenance badges on every layer; loading, no-data and stale states; validation panel; citizen preview.
- **9.5 Response Unit view.** Read-only tasks, larger touch targets, offline persistence of the last plan and map state; print and briefing export.
- **9.6 Advanced view (after gate).** 3D volumetric view with time-step animation and vertical exaggeration (choose Three.js or Cesium after a short spike); modular multi-format ingestion (NetCDF via xarray, delimited text) through a source registry.
- **9.7 Verification.** Color-blind simulator check on tiers; keyboard use; tap-to-reveal reasons on touch devices; timed usability test on the authorization task.
- **Gate:** badges correct against live, cached and simulated state; every hex-level indicator traces to a payload field; color-blind check passed; usability test run and its result recorded (no completion-time claim before then); simulated banner shown whenever any simulated layer is active.

### Phase 10. Demo readiness (S)
- Novel-location live test; cached fallback; everything simulated is labeled.
- Numbers reported only from actual runs.

---

## 3. Risks

| Risk | Mitigation |
|---|---|
| Synthetic data leaks into claims | `SIMULATED` provenance, CI leakage test, excluded from splits and metrics |
| Thin event data | Per-region counts reported by grade; design intent stated, not results |
| Real inventories lack precise dates or coordinates (confirmed for GSI's bulk inventory by GSI's own FAQ) | Use it for spatial context only; build the dated event set from NASA GLC/COOLR, Bhusanket incidence records, DFO and reconstructed events; drop the −1 h and −3 h samples where timing is uncertain; keep grade C records out of all metrics |
| Public sources disagree (Wayanad shows this clearly) | Triangulate at least 2–3 sources, store ranges, never use casualty counts or news rainfall as labels or features |
| NASA GLC/COOLR is a discontinued archive | Treat as fixed history; complement with GSI, DFO and self-built Sentinel-1 labels |
| Scope explosion | Ship E2 + E3 with a real back-test before E4, hardware or evacuation |
| Frontend rewrite cost | Build the hex and village layers first; console panels after |
| Storage migration breaks the old pipeline | Repository layer and a baseline tag; migrate one region first |
| Chronos-Bolt or TabPFN add complexity with no gain | Flagged and gated by the promotion test; drop if they don't earn a place |
| Alert path mistaken for official dissemination | Documented as a technical-readiness demo until an agency sponsors integration |
| Prototype mistaken for the product | It is a static page with simulated data, labeled as such; checklist K shows every item as prototype-only until built in the app |
| Design conflict between Cirrus and Section 13.3 | Resolution recorded in 0.4.1; update the architecture document so the two do not diverge |
| Hex rendering slows down at real hex counts (the prototype draws 150 SVG hexes) | Move to deck.gl; test at the target hex count before Phase 9 sign-off |
| Color-only or unverified accessibility | Word plus shape on every tier; run the color-blind simulator before claiming accessibility |
| Confidence and alert-resilience cues get conflated | Separate visual channels (desaturation versus corner dot), each traced to its own payload field |
| 3D view and ingestion expand scope | Deferred to 9.6, after the core gate |
| Basemap tile licence (the prototype styling assumes CARTO tiles) | Read the terms or self-host; the hex-first design works with no basemap |
| No hover on touch screens | Tap selects a hex and the panel shows its reason |

---

## 4. First actions (start here)

1. Tag the current repo as the baseline release.
2. Download SoilGrids rasters for the shortlist regions and record every data source's terms.
3. Add the `provenance` column with the three tags and the CI leakage test.
4. Download NASA GLC/COOLR, the DFO archive and the India Flood Inventory; open the GSI Bhukosh file and count, per region, how many records carry a usable date and time.
5. Reconstruct the first two events (Wayanad July 2024 and the Kerala 2018 monsoon) using the protocol in 0.3, and grade them.
6. Start Phase 1 (onboarding, catchments, villages) once steps 1 to 5 pass their Phase 0 gate.
7. Record the style decision (0.4.1) in the architecture document, replacing the teal, IBM Plex and "not a SaaS dashboard" wording in 13.3.
8. Move `cirrus.css` and `hydrasense-theme.css` into the frontend and render one token page (palette, type, tiers, badges) to review before building panels.
9. Freeze the payload contract in 0.4.2 so the prototype and the API agree before Phase 9.

## 5. What is still unverified

| Item | Why it matters | How to close it |
|---|---|---|
| Date and time fields in the GSI Bhukosh download | Decides how many events can support hour-level lead-time work. GSI's FAQ says temporal information is lacking, but I could not open the raw file | Download one region and inspect the attribute table |
| Terms of use for each event and data source | Some restrict production use | Read and record each licence in Phase 0 |
| Current status and format of NASA GLC/COOLR downloads | NASA states the project is discontinued | Confirm the file still downloads and note its date range (GLC covers 2007 to 2018) |
| Existing FoS implementation in `lead_time.py` | Must match the v2 equation, including the shared cos²β term | Compare code against v2 Section 7.2 |
| Whether −3 h and −1 h sampling offsets exist in the current sampler | Needed for any sub-6-hour claim | Inspect `ml/features/` sampling scripts |
| Actual number of dated events per region | Sets how strong any accuracy claim can be | Publish per-region counts by grade after Phase 0 |
| Figures for Indian national systems in v2 Section 3.1 | v2 itself says they must be re-verified before submission | Re-check against current sources |
| Existing frontend and API field names (current `/risk/map` response, current panels) | The 0.4.2 payload contract is a proposal and has not been compared with the codebase | Diff against the repo in Phase 9.1 |
| Color-blind distinguishability of the four tiers | Section 13.8 requires the check before any accessibility claim | Run a simulator on tier fills, badges and the confidence fade |
| Timed task-completion for a duty officer | Section 13.8 forbids a time claim until tested | Run the usability test in Phase 9.7 |
| Values Cirrus does not define (spacing, type sizes, focus ring, dark tokens, badge styles, motion timing) | The CSS layer chose them | Confirm against the source project |
| Terms for the CARTO basemap tiles assumed in the prototype styling | Some tile use is restricted | Read the terms or self-host tiles |
| deck.gl, h3-js and MapLibre versions and the corner-marker placement | The map layer file was not run against the real libraries | Pin versions and test in the app |
| `color-mix()` fills and touch behavior in Safari and on phones | The prototype was only run in a headless DOM | Test on real browsers and devices |
| Regional-language font resolved from the administrative lookup | Section 13.3 requires it; only a placeholder exists | Build with the boundary lookup in Phase 1 |
| Three.js versus Cesium for the 3D view | Sets effort for K22 | Short spike on one region's DEM |

Event details quoted in this document (for example Wayanad) come from public reports that disagree with each other; they illustrate the reconciliation method and are not final values.
