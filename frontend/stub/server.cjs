/**
 * stub/server.cjs — HydraSense Phase 12 Stub Server
 * -------------------------------------------------------
 * Local Express server on port 8001.
 * Implements all SRS §15 endpoints with data that cycles
 * through the SRS §20 five-stage demo escalation.
 *
 * Usage: node stub/server.cjs
 * Then run: npm run dev  (Vite proxies /api -> localhost:8001)
 *
 * Replace with Phase 8 (Guhan-10) FastAPI backend by changing
 * the Vite proxy target in vite.config.js.
 */

'use strict';
const express = require('express');
const app = express();
app.use(express.json());

// ---------------------------------------------------------------------------
// Pilot hex IDs — real H3 res-8 indices for Wayanad pilot cluster
// Computed via: h3.latlng_to_cell(lat, lng, 8) using h3 Python library
// ---------------------------------------------------------------------------
const PILOT_HEXES = [
  { hex_id: '8860064e61fffff', village: 'Mundakkai' },
  { hex_id: '8860064e63fffff', village: 'Mundakkai' },
  { hex_id: '8860064e65fffff', village: 'Mundakkai' },
  { hex_id: '8860064e67fffff', village: 'Mundakkai' },
  { hex_id: '8860064e69fffff', village: 'Mundakkai' },
  { hex_id: '8860064e29fffff', village: 'Mundakkai' },
  { hex_id: '8860064e2dfffff', village: 'Mundakkai' },
  { hex_id: '8860064e05fffff', village: 'Mundakkai' },
  { hex_id: '8860064e0dfffff', village: 'Mundakkai' },
  { hex_id: '8860064f59fffff', village: 'Mundakkai' },
  { hex_id: '8860064f5bfffff', village: 'Mundakkai' },
  { hex_id: '8860064e6bfffff', village: 'Chooralmala' },
  { hex_id: '8860064e41fffff', village: 'Chooralmala' },
  { hex_id: '8860064e43fffff', village: 'Chooralmala' },
  { hex_id: '8860064e45fffff', village: 'Chooralmala' },
  { hex_id: '8860064e4dfffff', village: 'Chooralmala' },
  { hex_id: '8860064e01fffff', village: 'Chooralmala' },
  { hex_id: '8860064e09fffff', village: 'Chooralmala' },
  { hex_id: '8860064e47fffff', village: 'Attamala' },
  { hex_id: '8860064e49fffff', village: 'Attamala' },
  { hex_id: '8860064e4bfffff', village: 'Attamala' },
  { hex_id: '8860064e55fffff', village: 'Attamala' },
  { hex_id: '8860064e5dfffff', village: 'Attamala' },
  { hex_id: '8860064e0bfffff', village: 'Attamala' },
  { hex_id: '8860064e6dfffff', village: 'Punjirimattom' },
  { hex_id: '8860064191fffff', village: 'Punjirimattom' },
  { hex_id: '8860064195fffff', village: 'Punjirimattom' },
  { hex_id: '88600641b1fffff', village: 'Punjirimattom' },
  { hex_id: '88600641b7fffff', village: 'Punjirimattom' },
];

// ---------------------------------------------------------------------------
// SRS §20 five-stage escalation — cycles every 12 seconds
// ---------------------------------------------------------------------------
const STAGES = [
  {
    // Stage 1 — Normal
    label: 'Normal',
    risk_score: 21, tier: 'Green', confidence_score: 91,
    lead_time_min: null, lead_time_basis: 'no_red_crossing_in_forecast_window',
    data_source: 'live', iot_anomaly_flag: false,
    factor_of_safety: 1.85,
    top_contributing_features: [
      { feature: 'rainfall_24h',               contribution: 0.12 },
      { feature: 'soil_saturation_ratio',       contribution: 0.10 },
      { feature: 'antecedent_precipitation_index', contribution: 0.08 },
      { feature: 'factor_of_safety',            contribution: 0.07 },
      { feature: 'ndvi_mean',                   contribution: 0.05 },
    ],
  },
  {
    // Stage 2 — Rainfall rising
    label: 'Rainfall rising',
    risk_score: 48, tier: 'Yellow', confidence_score: 84,
    lead_time_min: null, lead_time_basis: 'no_red_crossing_in_forecast_window',
    data_source: 'live', iot_anomaly_flag: false,
    factor_of_safety: 1.52,
    top_contributing_features: [
      { feature: 'rainfall_24h',               contribution: 0.28 },
      { feature: 'rain_intensity_mm_hr',        contribution: 0.22 },
      { feature: 'antecedent_precipitation_index', contribution: 0.18 },
      { feature: 'soil_saturation_ratio',       contribution: 0.14 },
      { feature: 'factor_of_safety',            contribution: 0.09 },
    ],
  },
  {
    // Stage 3 — Saturation building
    label: 'Saturation building',
    risk_score: 67, tier: 'Orange', confidence_score: 76,
    lead_time_min: null, lead_time_basis: 'no_red_crossing_in_forecast_window',
    data_source: 'live', iot_anomaly_flag: false,
    factor_of_safety: 1.15,
    top_contributing_features: [
      { feature: 'soil_saturation_ratio',       contribution: 0.31 },
      { feature: 'antecedent_precipitation_index', contribution: 0.26 },
      { feature: 'rainfall_72h_antecedent',     contribution: 0.20 },
      { feature: 'rainfall_24h',               contribution: 0.17 },
      { feature: 'factor_of_safety',            contribution: 0.12 },
    ],
  },
  {
    // Stage 4 — Slope response (FS drops below 1.0, CAP alert fires)
    label: 'Slope response',
    risk_score: 82, tier: 'Red', confidence_score: 88,
    lead_time_min: 120,   // t+2h forecast crossing — SRS §20 example
    lead_time_basis: 'forecast_crossing_t+2h',
    data_source: 'live', iot_anomaly_flag: false,
    factor_of_safety: 0.87,
    top_contributing_features: [
      { feature: 'factor_of_safety',            contribution: 0.38 },
      { feature: 'soil_saturation_ratio',       contribution: 0.30 },
      { feature: 'antecedent_precipitation_index', contribution: 0.22 },
      { feature: 'rainfall_24h',               contribution: 0.18 },
      { feature: 'simulated_ffgs_signal',       contribution: 0.14 },
    ],
  },
  {
    // Stage 5 — Decision (sensor goes offline → cached_demo)
    label: 'Decision',
    risk_score: 82, tier: 'Red', confidence_score: 88,
    lead_time_min: 120,
    lead_time_basis: 'forecast_crossing_t+2h',
    data_source: 'cached_demo', iot_anomaly_flag: true,  // sensor dropout
    factor_of_safety: 0.87,
    top_contributing_features: [
      { feature: 'factor_of_safety',            contribution: 0.38 },
      { feature: 'soil_saturation_ratio',       contribution: 0.30 },
      { feature: 'antecedent_precipitation_index', contribution: 0.22 },
      { feature: 'rainfall_24h',               contribution: 0.18 },
      { feature: 'simulated_ffgs_signal',       contribution: 0.14 },
    ],
  },
];

let stageIdx = 0;
const STAGE_INTERVAL_MS = 12_000;
setInterval(() => { stageIdx = (stageIdx + 1) % STAGES.length; }, STAGE_INTERVAL_MS);

function currentStage() { return STAGES[stageIdx]; }

// CAP alert — fires once stage reaches Red
let alertFired = false;
let alerts = [];
setInterval(() => {
  const s = currentStage();
  if (s.tier === 'Red' && !alertFired) {
    alertFired = true;
    alerts.push({
      alert_id: 'CAP-2026-001',
      type: 'cap',
      hex_id: PILOT_HEXES[0].hex_id,
      village: 'Mundakkai',
      timestamp: new Date().toISOString(),
      tier: 'Red',
      risk_score: s.risk_score,
      confidence_score: s.confidence_score,
      lead_time_min: s.lead_time_min,
      message: 'Critical landslide risk — Red tier threshold crossed. Evacuate to nearest shelter.',
      nearest_shelter: { name: 'Meppadi Government School', distance_m: 3200 },
    });
  }
  if (stageIdx === 0) { alertFired = false; alerts = []; } // reset on cycle
}, 2000);

// Downgrade event — added after Red when stage drops back
let downgradeFired = false;
setInterval(() => {
  const s = currentStage();
  if (s.tier !== 'Red' && stageIdx > 0 && alerts.length > 0 && !downgradeFired) {
    downgradeFired = true;
    alerts.push({
      alert_id: 'DOWNGRADE-2026-001',
      type: 'downgrade',
      hex_id: PILOT_HEXES[0].hex_id,
      village: 'Mundakkai',
      timestamp: new Date().toISOString(),
      tier: s.tier,
      message: 'Risk tier downgraded. Monitoring continues. 2 consecutive below-Orange cycles required to resolve.',
    });
  }
}, 3000);

// ---------------------------------------------------------------------------
// CORS — allow Vite dev server
// ---------------------------------------------------------------------------
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  next();
});

// ---------------------------------------------------------------------------
// Endpoints — SRS §15
// ---------------------------------------------------------------------------

// GET /risk/map
app.get('/risk/map', (req, res) => {
  const s = currentStage();
  const hexes = PILOT_HEXES.map((h, i) => {
    // Secondary hexes are one tier below the primary
    const tierOffset = i < 11 ? 0 : (i < 18 ? -1 : -2);
    const tiers = ['Green', 'Yellow', 'Orange', 'Red'];
    const idx = Math.max(0, tiers.indexOf(s.tier) + tierOffset);
    const tier = tiers[idx] || 'Green';
    const scoreMap = { Green: 21, Yellow: 48, Orange: 67, Red: 82 };
    return {
      hex_id: h.hex_id,
      village: h.village,
      risk_score: scoreMap[tier] + Math.floor(Math.random() * 5 - 2),
      tier,
      confidence_score: s.confidence_score,
      data_source: s.data_source,
    };
  });
  res.json(hexes);
});

// GET /risk/:hex_id
app.get('/risk/:hex_id', (req, res) => {
  const s = currentStage();
  res.json({
    hex_id: req.params.hex_id,
    risk_score: s.risk_score,
    tier: s.tier,
    confidence_score: s.confidence_score,
    lead_time_min: s.lead_time_min,
    lead_time_basis: s.lead_time_basis,
    top_contributing_features: s.top_contributing_features,
    data_source: s.data_source,
    iot_anomaly_flag: s.iot_anomaly_flag,
    factor_of_safety: s.factor_of_safety,
    demo_stage: s.label,
  });
});

// GET /risk/:hex_id/history
app.get('/risk/:hex_id/history', (req, res) => {
  const now = Date.now();
  const history = STAGES.flatMap((st, si) =>
    Array.from({ length: 4 }, (_, j) => ({
      timestamp: new Date(now - (STAGES.length - si) * STAGE_INTERVAL_MS + j * 3000).toISOString(),
      risk_score: st.risk_score + Math.floor(Math.random() * 4 - 2),
      tier: st.tier,
    }))
  );
  // Append a few current points
  const s = currentStage();
  for (let i = 0; i < 3; i++) {
    history.push({
      timestamp: new Date(now - (2 - i) * 3000).toISOString(),
      risk_score: s.risk_score + Math.floor(Math.random() * 3 - 1),
      tier: s.tier,
    });
  }
  res.json(history);
});

// GET /risk/:hex_id/inundation — SRS §15: only valid at Orange/Red
app.get('/risk/:hex_id/inundation', (req, res) => {
  const s = currentStage();
  const allowed = ['Orange', 'Red'].includes(s.tier);
  if (!allowed) {
    return res.status(403).json({ error: 'Inundation endpoint only available at tier >= Orange', tier: s.tier });
  }
  res.json({
    hex_id: req.params.hex_id,
    tier: s.tier,
    inundation_depth_m: s.tier === 'Red' ? 0.8 : 0.3,
    area_ha: 1.4,
    note: 'Simplified 2D estimate — static DEM-derived, not hydraulic model',
    timestamp: new Date().toISOString(),
  });
});

// GET /validation/loeo — static Phase 7 results
app.get('/validation/loeo', (_req, res) => {
  res.json({
    loeo_n_events: 30,
    loeo_n_detected: 0,
    detection_rate: 0.0,
    false_positive_rate: null,
    timing_error: { mean_min: null, median_min: null, min_min: null, max_min: null, n: 0 },
    data_completeness_note:
      'Rainfall features non-null ~65% of positive rows; factor_of_safety 0% non-null ' +
      '(Phase 3 DEM rasters not run). Detection rate improves once Phase 3 terrain + ' +
      'historical backfill exist. Harness is structurally correct — results are ' +
      'data-limited, not harness-limited.',
    scope: 'offline LOEO — computed once, not live',
    leakage_buffer_days: 7,
    detection_threshold: 'Orange or Red',
    run_timestamp_utc: '2026-09-06T12:00:00Z',
  });
});

// GET /alert/feed
app.get('/alert/feed', (_req, res) => res.json(alerts));

// GET /shelters/nearest/:hex_id
app.get('/shelters/nearest/:hex_id', (req, res) => {
  res.json([
    { shelter_id: 'S001', name: 'Meppadi Government School', lat: 11.5094, lon: 76.0667, distance_m: 3200 },
    { shelter_id: 'S002', name: 'Vythiri Community Hall',     lat: 11.5203, lon: 76.0523, distance_m: 4700 },
    { shelter_id: 'S003', name: 'Kalpetta District Hospital', lat: 11.6072, lon: 76.0824, distance_m: 9100 },
  ]);
});

// POST stubs (ingest) — accept and acknowledge
['rainfall', 'rainfall_forecast', 'soil_moisture', 'iot'].forEach((ep) => {
  app.post(`/ingest/${ep}`, (req, res) =>
    res.json({ status: 'accepted', endpoint: ep, rows: 1, note: 'stub — no persistence' })
  );
});
app.post('/alert/trigger', (req, res) =>
  res.json({ status: 'stub — alert trigger acknowledged' })
);

const PORT = 8001;
app.listen(PORT, () => {
  console.log(`\nHydraSense stub server running on http://localhost:${PORT}`);
  console.log('Cycling through SRS §20 demo stages every 12 seconds.');
  console.log('Stages: Normal -> Rainfall rising -> Saturation -> Slope response -> Decision\n');
});
