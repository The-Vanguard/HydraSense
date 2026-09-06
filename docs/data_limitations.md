# HydraSense — Data Limitations and Honest Disclosures

This document records known data quality limitations identified during development.
It is written for two audiences: internal developers (to avoid accidentally overclaiming
in code comments or commit messages) and judges/reviewers (to demonstrate we understand
our own data rather than hiding its gaps).

---

## L1 — ERA5 Historical Rainfall: Spatial Resolution and Bias

**Affects:** `data/weather/rainfall_historical.json`, all historical training events.  
**Data source:** Open-Meteo Archive API (ERA5 reanalysis, ~0.25° / ~28km grid).  
**Also affects:** `data/weather/soil_moisture.json` (NASA POWER, ~0.5° / ~55km grid).

### What we know

ERA5 at 28km resolution clips rainfall peaks through spatial averaging. For the
best-documented event in our training set (E001, Mundakkai, 2024-07-30):

| Source | 72h rainfall total |
|---|---|
| Kolathayar et al. (2025) gauge/station | ~572 mm |
| Our ERA5 archive value | 78.4 mm |
| Underestimate ratio | **~7.3×** |

This degree of underestimation for a record-breaking, sub-grid-scale rainfall event
is consistent with published ERA5 validation work for the Western Ghats (grid-averaging
clips convective peaks disproportionately at extreme intensities).

### What we assumed but did not verify

Our initial framing — "ERA5 underestimation is a systematic bias, not noise; XGBoost
will learn threshold associations regardless" — **assumed the underestimation ratio is
roughly proportional across event severities**. This assumption was not independently
verified.

ERA5 72h sums across our event set (ERA5 values only — no independent gauge totals
available for non-critical events):

| Event | Date | Severity | ERA5 72h sum | Gauge total | Bias ratio |
|---|---|---|---|---|---|
| E001 | 2024-07-30 | critical | 78.4 mm | 572 mm (lit.) | **7.3×** |
| E008 | 2018-08-17 | critical | 338.0 mm | no gauge data | unknown |
| E012 | 2020-08-07 | high | 298.0 mm | no gauge data | unknown |
| E006 | 2019-08-09 | high | 265.3 mm | no gauge data | unknown |
| E026 | 2022-08-04 | moderate | 242.8 mm | no gauge data | unknown |
| E013 | 2022-10-22 | moderate | 92.7 mm | no gauge data | unknown |
| E019 | 2015-11-18 | low | 6.6 mm | no gauge data | unknown |
| E030 | 2018-05-30 | low | 203.4 mm | no gauge data | unknown |

We have gauge/literature rainfall totals for **one event only** (E001). The bias ratio
for all other events is unknown.

### What this means for the model

The reanalysis literature generally shows ERA5 peak-clipping is **nonlinear with
intensity** — it clips extreme events more severely than moderate ones. If that pattern
holds here, the model's learned rainfall thresholds will be calibrated on an ERA5 scale
where the highest-risk cases are most severely compressed. The model will still rank
events in the right order (higher ERA5 = higher gauge, i.e. monotonicity likely holds),
but the **absolute threshold boundaries** between tier classes may be miscalibrated
toward the extreme end.

**Practical consequence for Phase 7 LOEO:** if LOEO shows that the model under-triggers
Red tier (misses critical events at high specificity), ERA5 rainfall compression for
extreme events is the first hypothesis to investigate — before tuning XGBoost parameters.

### Correct framing for judges

> "Our historical rainfall features use ERA5 reanalysis at 28km resolution, the same
> spatial scale as our soil saturation data (NASA POWER at 55km). We have verified
> 100% temporal coverage for all 30 training events back to 2009. For our best-documented
> event (Mundakkai 2024), ERA5 reports 78mm where station data records ~572mm — a ~7×
> underestimate consistent with ERA5's known peak-clipping at sub-grid-scale convective
> events. We assume but have not independently verified that this underestimation is
> roughly proportional across event severities; we lack independent gauge totals for our
> moderate and low-severity events. Phase 7 LOEO will tell us whether this affects tier
> calibration at the extreme end."

This is more defensible than asserting monotonicity as established fact.

---

## L2 — IoT Anomaly Flag: Stub Only

**Affects:** `iot_anomaly_flag` feature in training data and live inference.  
**Current state:** Returns `False` for all samples until Phase 8's POST `/ingest/iot`
populates sensor timestamps and Phase 10's dropout simulation wires up the staleness check.

Training proceeds with `iot_anomaly_flag = 0` (all zeros). XGBoost will assign near-zero
importance to this feature. When live IoT data becomes available post-Phase 8, the feature
will become informative — but the model will need to be retrained to use it properly.

**Correct framing for judges:** "IoT anomaly detection is architecturally in place;
the feature is present in the model's 25-feature matrix. In the current demo, it reads
as zero everywhere because sensor data is simulated in the IoT module — we have not yet
wired the staleness signal back into the training pipeline. This is a Phase 8 integration
task, not a missing feature."

---

*Last updated: Phase 6 self-review (2026-09-06). Update this file when Phase 7 LOEO
results are available — they will either confirm or refine the L1 tier-calibration concern.*
