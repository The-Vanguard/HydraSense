/**
 * BottomPanels.jsx — Event Replay (real past rainfall through the scorer), Scenario Simulator (what-if on the
 * selected hex's real inputs), Active Alerts (items held at the two-person gate).
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Line, XAxis, YAxis, ResponsiveContainer, ReferenceLine, Tooltip, Bar, ComposedChart } from 'recharts';
import axios from 'axios';
import { simulateRisk, approveGate, rejectGate, startExercise } from '../api/client';
import { getEventReplay } from './useDashboard';
import { TIER_COLOR, TIER_WORD, REGION_NAMES } from './tiers';
import { Stepper } from './VillageCard';

const api = axios.create({ baseURL: '/api', timeout: 30000 });

/* ───────────────────────── Event Replay ───────────────────────── */
export function EventReplay({ d, full = false }) {
  const regionCenter = d.regionStatus.find((r) => r.region_code === d.region)?.center;
  const options = useMemo(() => {
    let ev = d.events;
    if (!d.national && regionCenter) {
      ev = ev.filter((e) => Math.abs(e.lat - regionCenter.lat) < 0.6 && Math.abs(e.lon - regionCenter.lon) < 0.6);
    }
    const toKey = (s) => { const m = /^(\d{2})-(\d{2})-(\d{4})/.exec(s || ''); return m ? `${m[3]}${m[2]}${m[1]}` : s || ''; };
    return [...ev].sort((a, b) => toKey(b.date).localeCompare(toKey(a.date))).slice(0, 300);
  }, [d.events, d.national, regionCenter]);

  const [eventId, setEventId] = useState('');
  const [rep, setRep] = useState(null);
  const [loading, setLoading] = useState(false);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef(null);

  useEffect(() => { setEventId(options[0]?.event_id || ''); }, [options]);
  useEffect(() => {
    setRep(null); setI(0); setPlaying(false);
    if (!eventId) return;
    setLoading(true);
    getEventReplay(eventId).then((r) => { setRep(r); setI(Math.max(0, (r.steps?.length || 1) - 1)); })
      .catch(() => setRep({ steps: [], note: 'replay unavailable' })).finally(() => setLoading(false));
  }, [eventId]);
  useEffect(() => {
    clearInterval(timer.current);
    if (!playing || !rep?.steps?.length) return undefined;
    timer.current = setInterval(() => setI((x) => {
      if (x >= rep.steps.length - 1) { setPlaying(false); return x; }
      return x + 1;
    }), 500);
    return () => clearInterval(timer.current);
  }, [playing, rep]);

  const steps = rep?.steps || [];
  const cur = steps[i];
  const chart = steps.map((s) => ({ t: s.time.slice(11, 16), risk: s.risk_score, rain: s.rainfall_1h }));

  return (
    <div className="hs2-card">
      <div className="hs2-card-title">⏱ Event replay <span className="hs2-tag sim">Replay of a real past event</span></div>
      <select className="hs2-select" style={{ width: '100%', marginBottom: 8 }} value={eventId} onChange={(e) => setEventId(e.target.value)}>
        {options.length === 0 && <option value="">No recorded events for this region</option>}
        {options.map((e) => (
          <option key={e.event_id} value={e.event_id}>{(e.date || '').slice(0, 10)} · {(e.type || '').replace(/_/g, ' ')}{e.severity ? ` · ${e.severity}` : ''} · {e.event_id.split('::')[1] || e.region}</option>
        ))}
      </select>
      {loading && <div className="hs2-empty">Loading replay…</div>}
      {rep && !steps.length && !loading && <div className="hs2-empty">{rep.note}</div>}
      {steps.length > 0 && (
        <>
          <div style={{ height: full ? 200 : 110 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chart} margin={{ top: 4, right: 6, left: -26, bottom: 0 }}>
                <XAxis dataKey="t" tick={{ fontSize: 9 }} interval="preserveStartEnd" />
                <YAxis yAxisId="r" domain={[0, 100]} tick={{ fontSize: 9 }} />
                <YAxis yAxisId="mm" orientation="right" hide />
                <Tooltip contentStyle={{ fontSize: 11 }} />
                <Bar yAxisId="mm" dataKey="rain" name="rain mm/h" fill="#93c5fd" />
                <Line yAxisId="r" dataKey="risk" name="risk index" stroke="#dc2626" dot={false} strokeWidth={2} />
                <ReferenceLine yAxisId="r" y={55} stroke="#ea580c" strokeDasharray="3 3" />
                {cur && <ReferenceLine yAxisId="r" x={chart[i]?.t} stroke="#1d4ed8" />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <input type="range" className="hs2-range" min={0} max={steps.length - 1} value={i}
                 onChange={(e) => { setPlaying(false); setI(+e.target.value); }} aria-label="Replay time" />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5 }}>
            <button className="hs2-btn small primary" onClick={() => { if (i >= steps.length - 1) setI(0); setPlaying((p) => !p); }}>
              {playing ? '❚❚ Pause' : '▶ Play'}</button>
            <span className="num">{cur?.time.replace('T', ' ').slice(0, 16)}</span>
            <span>rain 24 h <span className="num">{cur?.rainfall_24h}</span> mm</span>
            <span style={{ marginLeft: 'auto', fontWeight: 700, color: TIER_COLOR[cur?.tier] }}>
              {cur ? `${Math.round(cur.risk_score)} · ${TIER_WORD[cur.tier]}` : ''}</span>
          </div>
          <div className="faint" style={{ fontSize: 10, marginTop: 4 }}>
            Real ERA5 rainfall, 24 h before the event · peak {rep.peak?.risk_score} ({rep.peak?.tier}) · terrain: {rep.terrain_source}.
            {full && ` ${rep.note}`}
          </div>
        </>
      )}
    </div>
  );
}

/* ───────────────────────── Scenario Simulator ───────────────────────── */
export function ScenarioSimulator({ d }) {
  const [rainPct, setRainPct] = useState(20);
  const [soilPts, setSoilPts] = useState(10);
  const [sensorFail, setSensorFail] = useState('no');
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const hex = d.selectedHexId;
  const regionCode = d.village?.region_code || d.selectedVillage?.region_code || (d.national ? null : d.region);

  const run = async () => {
    if (!hex) return;
    setBusy(true); setErr(null); setRes(null);
    try {
      let terrain = {};
      if (regionCode) {
        try { terrain = (await api.get(`/region/${regionCode}/static-features/${hex}`)).data; } catch { terrain = {}; }
      }
      const inp = d.risk?.inputs || {};
      const base = {
        hex_id: hex, slope_deg: terrain.slope_deg ?? undefined, hand_m: terrain.hand_m ?? undefined,
        elevation: terrain.elevation ?? undefined, TWI: terrain.TWI ?? undefined,
        rainfall_1h: inp.rainfall_1h ?? 0, rainfall_6h: inp.rainfall_6h ?? 0, rainfall_24h: inp.rainfall_24h ?? 0,
        rainfall_72h_antecedent: inp.rainfall_72h_antecedent ?? undefined,
        soil_saturation_ratio: inp.soil_saturation_ratio ?? undefined,
      };
      const k = 1 + rainPct / 100;
      const scen = {
        ...base,
        rainfall_1h: +(base.rainfall_1h * k).toFixed(2), rainfall_6h: +(base.rainfall_6h * k).toFixed(2),
        rainfall_24h: +(base.rainfall_24h * k).toFixed(2),
        rainfall_72h_antecedent: base.rainfall_72h_antecedent != null ? +(base.rainfall_72h_antecedent * k).toFixed(2) : undefined,
        soil_saturation_ratio: sensorFail === 'yes' ? undefined
          : base.soil_saturation_ratio != null ? Math.max(0, Math.min(1, base.soil_saturation_ratio + soilPts / 100)) : undefined,
      };
      const [b, s] = await Promise.all([simulateRisk(base), simulateRisk(scen)]);
      setRes({ b, s, terrainOk: terrain.slope_deg != null });
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Scenario failed.');
    } finally { setBusy(false); }
  };

  return (
    <div className="hs2-card">
      <div className="hs2-card-title">⚙ Scenario simulator <span className="hs2-tag sim">Simulated</span></div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 8, alignItems: 'end', fontSize: 11 }}>
        <label>Rainfall change
          <select className="hs2-select" style={{ width: '100%' }} value={rainPct} onChange={(e) => setRainPct(+e.target.value)}>
            {[-50, 0, 20, 50, 100, 200, 400].map((v) => <option key={v} value={v}>{v >= 0 ? '+' : ''}{v}%</option>)}
          </select></label>
        <label>Soil saturation
          <select className="hs2-select" style={{ width: '100%' }} value={soilPts} onChange={(e) => setSoilPts(+e.target.value)}>
            {[-20, -10, 0, 10, 20].map((v) => <option key={v} value={v}>{v >= 0 ? '+' : ''}{v} pts</option>)}
          </select></label>
        <label>Soil input lost
          <select className="hs2-select" style={{ width: '100%' }} value={sensorFail} onChange={(e) => setSensorFail(e.target.value)}>
            <option value="no">No</option><option value="yes">Yes</option>
          </select></label>
        <button className="hs2-btn primary small" disabled={!hex || busy} onClick={run}>{busy ? '…' : 'Run'}</button>
      </div>
      {!hex && <div className="hs2-empty">Select a village or hex first.</div>}
      {err && <div className="hs2-banner" style={{ marginTop: 8 }}>{err}</div>}
      {res && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
          {[['Baseline (current inputs)', res.b], ['Scenario', res.s]].map(([label, r]) => (
            <div key={label} className="hs2-tele">
              <div className="muted">{label}</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: TIER_COLOR[r.tier] }} className="num">{Math.round(r.risk_score)}
                <span style={{ fontSize: 11, marginLeft: 6 }}>{TIER_WORD[r.tier]}</span></div>
              <div className="faint">confidence {Math.round(r.confidence_score)} · lead {r.lead_time_min == null ? 'not projected' : `${Math.round(r.lead_time_min / 60)} h`}</div>
            </div>
          ))}
          <div className="faint" style={{ gridColumn: '1 / -1', fontSize: 10 }}>
            What-if only: nothing is stored or sent. Both runs use the same terrain
            {res.terrainOk ? ' (region GeoPackage)' : ' (terrain not found: slope/HAND missing)'}; soil strength
            parameters are not available to the simulator, so the numbers can differ from the live map score.
          </div>
        </div>
      )}
    </div>
  );
}

/* ───────────────────────── Active Alerts ───────────────────────── */
function AlertItem({ g, onDone }) {
  const [op, setOp] = useState('');
  const [role, setRole] = useState(g.roles_needed?.[0] || 'duty_officer');
  const [msg, setMsg] = useState(null);
  const needed = g.roles_needed?.[0];
  useEffect(() => { if (needed) setRole(needed); }, [needed]);   // offer the role that still has to approve
  const ctx = g.context || {};
  const tier = ctx.scenario_tier || (g.risk_score >= 75 ? 'Red' : 'Orange');
  const act = async (kind) => {
    if (!op.trim()) { setMsg('Enter your operator ID.'); return; }
    try {
      if (kind === 'reject') { await rejectGate(g.hex_id, op.trim(), role, 'rejected from dashboard'); onDone('Rejected. Nothing was sent.'); }
      else {
        const r = await approveGate(g.hex_id, op.trim(), role);
        if (r.action === 'held') setMsg(r.reason);
        else onDone(r.action === 'exercise_ready' ? `Exercise authorised (${r.alert_id}); CAP status=Exercise, nothing was sent.` : `Alert ${r.alert_id} authorised and released.`);
      }
      setOp('');
      onDone(null);
    } catch (e) { setMsg(e?.response?.data?.detail || 'Request failed.'); }
  };
  return (
    <div className={`hs2-alert ${g.exercise ? 'exercise' : tier === 'Orange' ? 'orange' : ''}`}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
        {g.exercise && <span className="hs2-tag sim">EXERCISE</span>}
        <strong>{TIER_WORD[tier]} {ctx.hazard || 'hazard'} risk</strong>
        <span className="muted">· {ctx.village || REGION_NAMES[ctx.region_code] || g.hex_id}</span>
        <span className="num faint" style={{ marginLeft: 'auto' }}>{new Date(g.created_at).toLocaleTimeString('en-IN', { hour12: false })}</span>
      </div>
      {ctx.what_is_happening && <div><strong>What is happening:</strong> {ctx.what_is_happening}</div>}
      {ctx.what_to_do && <div><strong>What to do:</strong> {ctx.what_to_do}</div>}
      <div style={{ margin: '6px 0' }}><Stepper gate={g} /></div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        <input className="hs2-input" style={{ flex: 1, minWidth: 80 }} placeholder="Operator ID" value={op} onChange={(e) => setOp(e.target.value)} />
        <select className="hs2-select" value={role} onChange={(e) => setRole(e.target.value)} style={{ fontSize: 11 }}>
          <option value="duty_officer">Duty officer</option><option value="district_authority">District authority</option>
        </select>
        <button className="hs2-btn small danger" onClick={() => act('approve')}>Approve</button>
        <button className="hs2-btn small" onClick={() => act('reject')}>Reject</button>
      </div>
      {msg && <div className="muted" style={{ marginTop: 4 }}>{msg}</div>}
    </div>
  );
}

export function ActiveAlerts({ d, onViewAll, full = false }) {
  const [notice, setNotice] = useState(null);
  const [exErr, setExErr] = useState(null);
  const list = full ? d.gates : d.gates.slice(0, 2);
  const exercise = async () => {
    setExErr(null);
    const code = d.national ? d.selectedVillage?.region_code : d.region;
    if (!code) { setExErr('Choose a region first.'); return; }
    try { await startExercise(code, 'Red'); d.reloadGates(); } catch (e) { setExErr(e?.response?.data?.detail || 'Could not start an exercise.'); }
  };
  return (
    <div className="hs2-card">
      <div className="hs2-card-title">🔔 Active alerts {d.gates.length > 0 && <span className="hs2-badge">{d.gates.length}</span>}
        <span className="right">
          <button className="hs2-btn small" onClick={exercise} title="Raise a labelled EXERCISE alert through the real two-person gate">+ Exercise</button>
          {!full && d.gates.length > 2 && <button className="hs2-btn small" style={{ marginLeft: 4 }} onClick={onViewAll}>View all</button>}
        </span></div>
      {exErr && <div className="hs2-banner" style={{ marginBottom: 6 }}>{exErr}</div>}
      {notice && <div className="hs2-tag live" style={{ marginBottom: 6, whiteSpace: 'normal' }}>{notice}</div>}
      {list.length === 0 && <div className="hs2-empty">No alerts awaiting authorisation.</div>}
      {list.map((g) => <AlertItem key={g.hex_id} g={g} onDone={(t) => { if (t) setNotice(t); d.reloadGates(); }} />)}
    </div>
  );
}
