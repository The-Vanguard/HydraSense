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
