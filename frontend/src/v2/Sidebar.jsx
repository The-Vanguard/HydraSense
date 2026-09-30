/**
 * Sidebar.jsx — quick regional views, focus corridors, live input status, onboarding, activity log.
 */
import React, { useState } from 'react';
import { resolveRegion } from '../api/client';
import { STATE_VIEWS, CORRIDORS, NATIONAL_CODE } from './sidebarConst';

function logText(m) {
  switch (m.type) {
    case 'tier_change': return `${m.hex_id?.slice(0, 9)} → ${m.tier} (${Math.round(m.risk_score ?? 0)})`;
    case 'persist_declared': return `Persistent threat ${m.hex_id?.slice(0, 9)} (${m.cycles} cycles)`;
    case 'gate_pending': return `${m.exercise ? 'EXERCISE ' : ''}alert held for authorisation`;
    case 'gate_approved': return `Authorisation recorded (${m.operator_id})`;
    case 'gate_rejected': return `Alert rejected (${m.operator_id})`;
    case 'telemetry_tick': return `SIMULATED sensor tick (${m.sensor_type || 'sensor'})`;
    case 'sensor_offline': return 'SIMULATED sensor offline (fallback demo)';
    default: return m.type;
  }
}

export default function Sidebar({ region, onRegion, rainSource, soilSat, wsMessages, onInspect, onOnboarded }) {
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [showLog, setShowLog] = useState(false);

  const resolve = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true); setMsg(null);
    try {
      const r = await resolveRegion(query.trim());
      if (r?.region_code) {
        setMsg(`Onboarded ${r.label || r.region_code} (${r.hex_count ?? '?'} hexes). Scores appear after a scoring cycle.`);
        onOnboarded?.(r.region_code);
      } else setMsg('Could not resolve that place.');
    } catch (err) {
      setMsg(err?.response?.data?.detail || 'Onboarding failed (it can take several minutes; try again).');
    } finally { setBusy(false); }
  };

  const rainState = !rainSource ? { cls: '', text: 'no current scores' }
    : /live/.test(rainSource) ? { cls: 'live', text: 'Live' }
    : rainSource === 'sensor' ? { cls: 'sim', text: 'Simulated' } : { cls: 'warn', text: 'Fallback' };

  return (
    <aside className="hs2-side">
      <div className="hs2-card">
        <div className="hs2-card-title">📍 Quick regional views</div>
        <div className="hs2-navlist">
          {STATE_VIEWS.map((s) => (
            <button key={s.label} className={`hs2-navitem${s.regions.includes(region) ? ' is-active' : ''}`}
                    onClick={() => onRegion(s.regions[0])}>{s.label}</button>
          ))}
          <button className={`hs2-navitem${region === NATIONAL_CODE ? ' is-active' : ''}`}
                  onClick={() => onRegion(NATIONAL_CODE)}>All India (national overview)</button>
        </div>
      </div>

      <div className="hs2-card">
        <div className="hs2-card-title">⊕ Focus corridors</div>
        <div className="hs2-chipgrid">
          {CORRIDORS.map((c) => (
            <button key={c.code} className={`hs2-navitem${region === c.code ? ' is-active' : ''}`}
                    onClick={() => onRegion(c.code)} style={{ fontSize: 11 }}>{c.label}</button>
          ))}
        </div>
        <form onSubmit={resolve} style={{ display: 'flex', gap: 5, marginTop: 8 }}>
          <input className="hs2-input" style={{ flex: 1 }} placeholder="Onboard any hill area…" value={query}
                 onChange={(e) => setQuery(e.target.value)} />
          <button className="hs2-btn small" disabled={busy}>{busy ? '…' : 'Go'}</button>
        </form>
        {msg && <div className="muted" style={{ fontSize: 11, marginTop: 5 }}>{msg}</div>}
      </div>

      <div className="hs2-card">
        <div className="hs2-card-title">〰 Live hydro-telemetry</div>
        <div className="hs2-tele">
          <div style={{ display: 'flex' }}><strong>Rainfall</strong>
            <span className={`hs2-tag ${rainState.cls}`} style={{ marginLeft: 'auto' }}>{rainState.text}</span></div>
          <div className="muted">{rainSource || '—'} · IMERG → Open-Meteo → cached</div>
        </div>
        <div className="hs2-tele">
          <div><strong>Soil moisture</strong></div>
          <div className="muted">Open-Meteo model proxy{soilSat != null ? ` · ${Math.round(soilSat * 100)}% saturation (selected hex)` : ''}</div>
        </div>
        <div className="hs2-tele">
          <div style={{ display: 'flex' }}><strong>Sensor status</strong>
            <span className="hs2-tag" style={{ marginLeft: 'auto' }}>none deployed</span></div>
          <div className="muted">No field nodes; sensor ticks in the log are simulated.</div>
        </div>
        <div className="hs2-tele">
          <div><strong>Data-source fallback chain</strong></div>
          <div className="muted">Local sensor → satellite (IMERG) → model (Open-Meteo) → cached</div>
        </div>
        <button className="hs2-btn primary" style={{ width: '100%', justifyContent: 'center', marginTop: 10 }}
                onClick={onInspect}>⚙ Inspect &amp; debug predictions</button>
      </div>

      <div className="hs2-card">
        <button className="hs2-card-title" onClick={() => setShowLog((s) => !s)}
                style={{ border: 0, background: 'none', width: '100%', cursor: 'pointer', padding: 0, margin: 0 }}>
          ☰ Activity log <span className="right muted">{wsMessages.length} · {showLog ? 'hide' : 'show'}</span>
        </button>
        {showLog && (
          <div style={{ maxHeight: 220, overflow: 'auto', marginTop: 8, fontSize: 11 }}>
            {wsMessages.length === 0 && <div className="hs2-empty">No events yet.</div>}
            {wsMessages.map((m, i) => (
              <div key={i} style={{ padding: '3px 0', borderBottom: '1px solid var(--c-border)' }}>
                <span className="num faint">{new Date(m._at).toLocaleTimeString('en-IN', { hour12: false })}</span>{' '}
                {logText(m)}
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
