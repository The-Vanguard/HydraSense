/**
 * api/client.js — HydraSense Phase 12
 * Axios wrapper for all SRS §15 endpoints.
 * Single source for backend URL — swap Vite proxy target in vite.config.js
 * when Phase 8 (Guhan-10) backend is ready.
 */
import axios from 'axios';

const api = axios.create({ baseURL: '/api', timeout: 8000 });

/** GET /risk/map — all pilot hex risk scores */
export const getRiskMap = (bbox = null, region = null) => {
  const params = {};
  if (bbox) params.bbox = Array.isArray(bbox) ? bbox.join(',') : bbox;
  if (region) params.region = region;
  return api.get('/risk/map', { params }).then((r) => r.data);
};

/** GET /region/list — list of all 10 onboarded regions */
export const getRegionsList = () =>
  api.get('/region/list').then((r) => r.data);

/** POST /region/resolve — autonomous region onboarding */
export const resolveRegion = (query, force = false) =>
  api.post(`/region/resolve?query=${encodeURIComponent(query)}${force ? '&force=true' : ''}`).then((r) => r.data);

/** POST /simulate/iot-toggle — deliberate IoT sensor failure demonstration (§14.5) */
export const toggleIoTSensor = (sensorId = 'IOT_WAYANAD_001') =>
  api.post(`/simulate/iot-toggle?sensor_id=${encodeURIComponent(sensorId)}`).then((r) => r.data);

/** GET /risk/{hex_id} — full risk record for one hex */
export const getRisk = (hexId) =>
  api.get(`/risk/${hexId}`).then((r) => r.data);

/** GET /risk/{hex_id}/history — time series for trend line */
export const getRiskHistory = (hexId) =>
  api.get(`/risk/${hexId}/history`).then((r) => r.data);

/**
 * GET /risk/{hex_id}/inundation — 2D inundation.
 * SRS §15: ONLY call when tier >= Orange; endpoint is gated server-side too.
 */
export const getInundation = (hexId) =>
  api.get(`/risk/${hexId}/inundation`).then((r) => r.data);

/** GET /validation/loeo — static LOEO results (Phase 7 output) */
export const getLoeoResults = () =>
  api.get('/validation/loeo').then((r) => r.data);

/** GET /alert/feed — CAP alerts + downgrade events */
export const getAlertFeed = () =>
  api.get('/alert/feed').then((r) => r.data);

/**
 * GET /risk/{hex_id}/uncertainty — real Phase 5 factor-of-safety (+ band) for
 * a real Wayanad hex, computed from real observations.dynamic_features.
 * Returns nulls (with an honest band_note) for hexes with no real terrain
 * static_features recorded yet -- never a fabricated FS value.
 */
export const getUncertainty = (hexId) =>
  api.get(`/risk/${hexId}/uncertainty`).then((r) => r.data);

/** GET /shelters/nearest/{hex_id} — nearest static shelter lookup */
export const getNearestShelter = (hexId) =>
  api.get(`/shelters/nearest/${hexId}`).then((r) => r.data);

/**
 * GET /events/map — real sourced historical flood/landslide events
 * (Phase 13 multiregion dataset). NOT a live model output — each entry
 * carries data_source_note saying so; render distinctly from live risk hexes.
 */
export const getEventsMap = (bbox = null) => {
  const params = bbox ? { bbox: bbox.join(',') } : {};
  return api.get('/events/map', { params }).then((r) => r.data);
};

/**
 * GET /events/{event_id}/rainfall-window — real hourly ERA5 rainfall for the
 * 24h before this specific event's recorded timestamp. Empty series (with an
 * honest note) when real ingestion doesn't cover that date -- never faked.
 */
export const getEventRainfallWindow = (eventId) =>
  api.get(`/events/${eventId}/rainfall-window`).then((r) => r.data);

/**
 * POST /simulate/risk — manual "what-if" scenario, scored by the real
 * trained Wayanad FusionModel. Fires a real ntfy.sh alert on Orange/Red
 * (server-side dedup). Fields are all optional; sparse input gets an
 * honest warning back instead of a silently misleading flat score.
 */
export const simulateRisk = (scenario) =>
  api.post('/simulate/risk', scenario).then((r) => r.data);

/** GET /simulate/points — real Wayanad pilot hexes to start a manual scenario from. */
export const getSimulationPoints = () =>
  api.get('/simulate/points').then((r) => r.data);

// ── Stage 6 additions ──────────────────────────────────────────────────────

/** GET /validation/loro — LORO (Leave-One-Region-Out) 10-fold results */
export const getLoroResults = () =>
  api.get('/validation/loro').then((r) => r.data);

/** GET /confidence/{hex_id}/breakdown — 3-factor confidence breakdown */
export const getConfidenceBreakdown = (hexId) =>
  api.get(`/confidence/${hexId}/breakdown`).then((r) => r.data);

/** GET /confidence/{hex_id}/persistent — Persistent Threat state */
export const getPersistentThreat = (hexId) =>
  api.get(`/confidence/${hexId}/persistent`).then((r) => r.data);

/** GET /alert/gate/pending — pending Red alert gate requests */
export const getPendingGates = () =>
  api.get('/alert/gate/pending').then((r) => r.data);

/** GET /alert/gate/{hex_id} — gate state for a specific hex */
export const getGateState = (hexId) =>
  api.get(`/alert/gate/${hexId}`).then((r) => r.data);

/** POST /alert/gate/approve — two-person gate approval (needs 2 different operators, roles duty_officer + district_authority) */
export const approveGate = (hexId, operatorId, role) =>
  api.post('/alert/gate/approve', { hex_id: hexId, operator_id: operatorId, role }).then((r) => r.data);

/** POST /alert/gate/reject — either role rejects a pending alert */
export const rejectGate = (hexId, operatorId, role, reason = '') =>
  api.post('/alert/gate/reject', { hex_id: hexId, operator_id: operatorId, role, reason }).then((r) => r.data);

/**
 * createAlertWebSocket — connect directly to the FastAPI backend WebSocket.
 * Bypasses the Vite dev proxy (which cannot reliably handle WS upgrades).
 * In dev: ws://localhost:8000/ws/alerts
 * In prod: wss://<same-host>/ws/alerts
 */
export const createAlertWebSocket = () => {
  const isDev  = window.location.port === '5173';
  const proto  = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host   = isDev ? 'localhost:8000' : window.location.host;
  return new WebSocket(`${proto}://${host}/ws/alerts`);
};
