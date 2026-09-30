/**
 * useDashboard.js — all live data for the v2 dashboard, from the real backend endpoints only.
 * Nothing here invents a value: a missing value stays null and the UI says why.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getRiskMap, getRisk, getRiskHistory, getRegionStatus, getPendingGates, createAlertWebSocket,
  getEventsMap, getConfidenceFactors, getVillagePriority,
} from '../api/client';
import axios from 'axios';

const api = axios.create({ baseURL: '/api', timeout: 60000 });
export const NATIONAL = 'all-india';

export const getVillageSummary = (region) =>
  api.get('/village/summary', { params: region && region !== NATIONAL ? { region } : {} }).then((r) => r.data);
export const getVillageRisk = (villageId, region) =>
  api.get(`/village/${villageId}/risk`, { params: { region } }).then((r) => r.data);
export const getEventReplay = (eventId) =>
  api.get(`/events/${encodeURIComponent(eventId)}/replay`).then((r) => r.data);

function usePoll(fn, ms, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const gen = useRef(0);                  // responses for an older set of deps (e.g. previous region) are dropped
  const run = useCallback(() => {
    const my = gen.current;
    fn().then((d) => { if (my === gen.current) { setData(d); setError(null); } })
      .catch((e) => { if (my === gen.current) setError(e?.response?.data?.detail || e?.message || 'unavailable'); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    gen.current += 1;
    setData(null); setError(null);
    run();
    const iv = setInterval(run, ms);
    return () => clearInterval(iv);
  }, [run, ms]);
  return { data, error, reload: run };
}

export default function useDashboard() {
  const [region, setRegion] = useState(() => {
    try { return localStorage.getItem('hs2-region') || NATIONAL; } catch { return NATIONAL; }
  });
  const [selectedHexId, setSelectedHexId] = useState(null);
  const [selectedVillage, setSelectedVillage] = useState(null);   // {village_id, region_code}
  const [wsMessages, setWsMessages] = useState([]);
  const [backendUp, setBackendUp] = useState(null);
  const national = region === NATIONAL;

  useEffect(() => { try { localStorage.setItem('hs2-region', region); } catch { /* ignore */ } }, [region]);

  // ── polled data ────────────────────────────────────────────────────────
  const regionStatus = usePoll(() => getRegionStatus(), 60_000, []);
  const summary = usePoll(() => getVillageSummary(region), 90_000, [region]);
  const hexes = usePoll(() => (national ? Promise.resolve([]) : getRiskMap(null, region)), 30_000, [region]);
  const villages = usePoll(() => (national ? Promise.resolve(null) : getVillagePriority(region, 500)),
    90_000, [region]);
  const gates = usePoll(() => getPendingGates().then((d) => d.pending_gates || []), 5_000, []);
  const events = usePoll(() => getEventsMap(), 600_000, []);

  useEffect(() => { setBackendUp(regionStatus.error ? false : regionStatus.data ? true : null); },
    [regionStatus.data, regionStatus.error]);

  // Default selection: the highest-value village of the region (or of all regions when national).
  const autoRef = useRef(null);
  useEffect(() => {
    const top = summary.data?.top_village;
    const key = `${region}|${top?.village_id}`;
    if (!top || autoRef.current === key) return;
    if (region !== NATIONAL && top.region_code && top.region_code !== region) return;   // belongs to another region
    autoRef.current = key;
    setSelectedVillage({ village_id: top.village_id, region_code: top.region_code || region });
  }, [summary.data, region]);

  // Village record -> its lead hex drives the hex detail.
  const [village, setVillage] = useState(null);
  const [villageErr, setVillageErr] = useState(null);
  useEffect(() => {
    setVillage(null); setVillageErr(null);
    if (!selectedVillage) return undefined;
    let alive = true;
    const load = () => getVillageRisk(selectedVillage.village_id, selectedVillage.region_code)
      .then((v) => { if (!alive) return; setVillage(v); if (v.lead_hex_id) setSelectedHexId(v.lead_hex_id); })
      .catch((e) => alive && setVillageErr(e?.response?.data?.detail || 'village unavailable'));
    load();
    const iv = setInterval(load, 90_000);
    return () => { alive = false; clearInterval(iv); };
  }, [selectedVillage]);

  // Hex detail: risk, history, confidence factors.
  const [risk, setRisk] = useState(null);
  const [history, setHistory] = useState([]);
  const [factors, setFactors] = useState(null);
  useEffect(() => {
    setRisk(null); setHistory([]); setFactors(null);
    if (!selectedHexId) return undefined;
    let alive = true;
    const load = () => {
      getRisk(selectedHexId).then((r) => alive && setRisk(r)).catch(() => {});
      getRiskHistory(selectedHexId).then((h) => alive && setHistory(Array.isArray(h) ? h : [])).catch(() => {});
      getConfidenceFactors(selectedHexId).then((f) => alive && setFactors(f)).catch(() => alive && setFactors(null));
    };
    load();
    const iv = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, [selectedHexId]);

  // ── WebSocket activity log (snapshot + deltas) ───────────────────────────
  useEffect(() => {
    let ws; let timer; let delay = 5000; let closed = false;
    const connect = () => {
      try {
        ws = createAlertWebSocket();
        ws.onopen = () => { delay = 5000; };
        ws.onmessage = (evt) => {
          try {
            const msg = JSON.parse(evt.data);
            if (msg.type === 'snapshot') return;
            setWsMessages((prev) => [{ ...msg, _at: new Date().toISOString() }, ...prev].slice(0, 150));
            if (msg.type && msg.type.startsWith('gate_')) gates.reload();
          } catch { /* ignore malformed */ }
        };
        ws.onclose = () => { if (!closed) { timer = setTimeout(connect, delay); delay = Math.min(delay * 2, 60000); } };
      } catch { /* ignore */ }
    };
    connect();
    return () => { closed = true; clearTimeout(timer); if (ws) ws.close(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectRegion = useCallback((code) => {
    setRegion(code);
    setSelectedHexId(null);
    setSelectedVillage(null);
    autoRef.current = null;
  }, []);

  const selectVillage = useCallback((v) => setSelectedVillage(v), []);
  const selectHex = useCallback((h) => { setSelectedVillage(null); setVillage(null); setSelectedHexId(h); }, []);

  return {
    region, national, selectRegion,
    regionStatus: regionStatus.data?.regions || [],
    summary: summary.data, summaryError: summary.error,
    hexes: Array.isArray(hexes.data) ? hexes.data : [],
    villages: villages.data, villagesError: villages.error,
    gates: gates.data || [], reloadGates: gates.reload,
    events: Array.isArray(events.data) ? events.data : [],
    selectedHexId, selectHex, selectedVillage, selectVillage, village, villageErr,
    risk, history, factors,
    wsMessages, backendUp,
  };
}
