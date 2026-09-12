/**
 * api/client.js — HydraSense Phase 12
 * Axios wrapper for all SRS §15 endpoints.
 * Single source for backend URL — swap Vite proxy target in vite.config.js
 * when Phase 8 (Guhan-10) backend is ready.
 */
import axios from 'axios';

const api = axios.create({ baseURL: '/api', timeout: 8000 });

/** GET /risk/map — all pilot hex risk scores */
export const getRiskMap = (bbox = null) => {
  const params = bbox ? { bbox: bbox.join(',') } : {};
  return api.get('/risk/map', { params }).then((r) => r.data);
};

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
 * GET /events/tabpfn-importance — GLOBAL permutation feature importance for
 * the TabPFN model (Step 6c). Same ranking for every event, not a live or
 * per-prediction value — fetch once, not per event.
 */
export const getTabpfnImportance = () =>
  api.get('/events/tabpfn-importance').then((r) => r.data);

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
