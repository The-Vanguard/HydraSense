/**
 * LeftColumn.jsx — GIS Control & Institutional Record Sidebar
 * Matches exact UI/UX from reference.jpeg:
 *  - Header: Mountain icon + "MULTI-REGION HAZARD MAP"
 *  - Status badges (onboarded regions, live-weather scoring, scoring method)
 *  - SPATIAL STATE SCOPE select
 *  - QUICK REGIONAL VIEWS pill buttons (Tamil Nadu, Kerala, Uttarakhand, Himachal, All India, Reset)
 *  - "Inspect & Debug Predictions" blue pill button
 *  - FOCUS NATIONAL CORRIDORS 2-column pill grid
 *  - REAL-TIME HYDRO-TELEMETRY status card
 *  - Collapsible FORCE STATUS & AUDIT LOG (tamper-evident feed & gate records)
 */
import React, { useState, useEffect, useRef } from 'react';

const TIER_COLOR = {
  Green:  '#10b981',
  Yellow: '#f59e0b',
  Orange: '#f97316',
  Red:    '#ef4444',
};

const CORRIDORS = [
  { label: 'Nilgiris (TN)',     code: 'nilgiris-tn' },
  { label: 'Wayanad (KL)',      code: 'wayanad-kl' },
  { label: 'Kedarnath (UK)',    code: 'rudraprayag-uk' },
  { label: 'Manali (HP)',       code: 'kullu-hp' },
  { label: 'Mahabaleshwar (MH)',code: 'idukki-kl' },
  { label: 'Darjeeling (WB)',   code: 'darjeeling-wb' },
];

const REGIONAL_VIEWS = [
  { label: 'Tamil Nadu',  code: 'nilgiris-tn' },
  { label: 'Kerala',      code: 'wayanad-kl' },
  { label: 'Uttarakhand', code: 'rudraprayag-uk' },
  { label: 'Himachal',    code: 'kullu-hp' },
  { label: 'All India',   code: 'all-india' },
];

function timestamp() {
  return new Date().toLocaleTimeString('en-IN', { hour12: false });
}

function auditHash(entry) {
  let h = 0;
  for (const ch of JSON.stringify(entry)) h = (Math.imul(31, h) + ch.charCodeAt(0)) | 0;
  return Math.abs(h).toString(16).padStart(8, '0');
}

export default function LeftColumn({
  wsAlerts = [],
  pendingGates = [],
  selectedRegionCode = 'wayanad-kl',
  onRegionChange,
  onDebugClick,
}) {
  const [feed, setFeed]                 = useState([]);
  const [pulse, setPulse]               = useState(null);
  const [showAuditFeed, setShowAudit]   = useState(false);
  const [stateScope, setStateScope]     = useState('All India (National Overview)');
  const feedRef                         = useRef(null);
  const processedRef                    = useRef(new Set());

  // Convert WS alert messages into feed entries
  useEffect(() => {
    const newEntries = [];
    wsAlerts.forEach(msg => {
      const key = `${msg.type}-${msg.hex_id || ''}-${msg.sensor_id || ''}-${msg.timestamp || ''}-${msg.tick || ''}-${msg.cycles || ''}`;
      if (!processedRef.current.has(key)) {
        processedRef.current.add(key);
        const entry = {
          id: `${Date.now()}-${Math.random()}`,
          ts: timestamp(),
          type: msg.type,
          tier: msg.tier || (msg.status === 'offline' ? 'Orange' : msg.type === 'telemetry_tick' ? 'Green' : undefined),
          hex: msg.hex_id,
          text: buildText(msg),
          raw: msg,
        };
        newEntries.push(entry);

        if (msg.tier === 'Red' || msg.type === 'alert_fired' || msg.type === 'sensor_status_changed') {
          setPulse(entry.id);
          setTimeout(() => setPulse(null), 800);
        }
      }
    });

    if (newEntries.length > 0) {
      setFeed(prev => [...newEntries, ...prev].slice(0, 100));
    }
  }, [wsAlerts]);

  // Pending gate entries
  const gateEntries = pendingGates.map(g => ({
    id: g.hex_id,
    ts: g.opened_at ? new Date(g.opened_at * 1000).toLocaleTimeString('en-IN', { hour12: false }) : '—',
    type: 'gate_pending',
    tier: 'Red',
    hex: g.hex_id,
    text: `AUTH pending — risk ${g.risk_score?.toFixed(0)}`,
    raw: g,
  }));

  const allEntries = [...gateEntries, ...feed];

  const handleSelectRegion = (code) => {
    onRegionChange?.(code);
    const found = REGIONAL_VIEWS.find(r => r.code === code) || CORRIDORS.find(c => c.code === code);
    if (found) {
      setStateScope(`${found.label} Sector`);
    }
  };

  const handleReset = () => {
    handleSelectRegion('wayanad-kl');
    setStateScope('All India (National Overview)');
  };

  return (
    <aside className="ref-left-sidebar">
      {/* ── Title Area: Mountain Icon + Title ── */}
      <div className="ref-sidebar-header">
        <div className="ref-sidebar-title-row">
          <svg className="ref-mountain-icon" width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path
              d="M3 20L9 10L14 17L17 13L21 20H3Z"
              stroke="#f97316"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className="ref-sidebar-title">MULTI-REGION HAZARD MAP</span>
        </div>

        {/* Live Feed Status Pill Tags */}
        <div className="ref-tags-container">
          <div className="ref-tag-pill ref-tag-pill--mint">
            10 onboarded districts · Himalaya, Western Ghats, Northeast
          </div>
          <div className="ref-tag-pill ref-tag-pill--red">
            <span>LIVE WEATHER · SAMPLED HEXES PER DISTRICT</span>
          </div>
          <div className="ref-tag-pill ref-tag-pill--blue">
            <span>SCORING: PHYSICS-FIRST INDEX (UNCALIBRATED)</span>
          </div>
        </div>
      </div>

      {/* ── Section: SPATIAL STATE SCOPE ── */}
      <div className="ref-sidebar-section">
        <div className="ref-section-label">SPATIAL STATE SCOPE</div>
        <div className="ref-scope-select-wrap">
          <span className="ref-scope-prefix">IN</span>
          <select
            value={stateScope}
            onChange={(e) => {
              setStateScope(e.target.value);
              if (e.target.value.includes('Kerala')) handleSelectRegion('wayanad-kl');
              else if (e.target.value.includes('Tamil Nadu')) handleSelectRegion('nilgiris-tn');
              else if (e.target.value.includes('Uttarakhand')) handleSelectRegion('rudraprayag-uk');
              else if (e.target.value.includes('Himachal')) handleSelectRegion('kullu-hp');
            }}
            className="ref-scope-select"
          >
            <option value="All India (National Overview)">All India (National Overview)</option>
            <option value="Kerala (Wayanad / Idukki)">Kerala (Wayanad / Idukki)</option>
            <option value="Tamil Nadu (Nilgiris)">Tamil Nadu (Nilgiris)</option>
            <option value="Uttarakhand (Rudraprayag / Chamoli)">Uttarakhand (Rudraprayag / Chamoli)</option>
            <option value="Himachal Pradesh (Kullu)">Himachal Pradesh (Kullu)</option>
            <option value="Sikkim / West Bengal">Sikkim / West Bengal</option>
          </select>
        </div>
      </div>

      {/* ── Section: QUICK REGIONAL VIEWS ── */}
      <div className="ref-sidebar-section">
        <div className="ref-section-label">QUICK REGIONAL VIEWS</div>
        <div className="ref-quick-views-grid">
          {REGIONAL_VIEWS.map((reg) => {
            const isActive = selectedRegionCode === reg.code;
            return (
              <button
                key={reg.code}
                onClick={() => handleSelectRegion(reg.code)}
                className={`ref-pill-btn${isActive ? ' is-active' : ''}`}
              >
                {reg.code !== 'all-india' && <span className="ref-pill-btn-icon">📍</span>}
                <span>{reg.label}</span>
              </button>
            );
          })}
          <button onClick={handleReset} className="ref-pill-btn ref-pill-btn--reset" title="Reset View">
            <span>⟲ Reset</span>
          </button>
        </div>
      </div>

      {/* ── Primary Action: Inspect & Debug Predictions Button ── */}
      <button
        onClick={onDebugClick}
        className="ref-btn-primary"
        title="Inspect ML predictions, geotechnical factors and spatial CV metrics"
      >
        <span className="ref-btn-icon">⚙️</span>
        <span>Inspect & Debug Predictions</span>
      </button>

      {/* ── Section: FOCUS NATIONAL CORRIDORS ── */}
      <div className="ref-sidebar-section">
        <div className="ref-section-label">FOCUS NATIONAL CORRIDORS</div>
        <div className="ref-corridors-grid">
          {CORRIDORS.map((cor) => {
            const isSelected = selectedRegionCode === cor.code;
            return (
              <button
                key={cor.code}
                onClick={() => handleSelectRegion(cor.code)}
                className={`ref-corridor-pill${isSelected ? ' is-selected' : ''}`}
              >
                <span className="ref-target-icon">🎯</span>
                <span>{cor.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Section: REAL-TIME HYDRO-TELEMETRY ── */}
      <div className="ref-sidebar-section">
        <div className="ref-section-label">REAL-TIME HYDRO-TELEMETRY</div>
        <div className="ref-telemetry-card">
          <div className="ref-telemetry-top">
            <span className="ref-telemetry-brand">📡 NASA IMERG & SMAP Live</span>
            <span className="ref-live-tag">Live Feed</span>
          </div>
          <div className="ref-telemetry-sub">
            <strong>Precipitation:</strong> NASA GPM IMERG (~4h latency)
          </div>
        </div>
      </div>

      {/* ── Collapsible: FORCE STATUS & AUDIT FEED ── */}
      <div className="ref-audit-collapsible">
        <button
          className="ref-audit-toggle-btn"
          onClick={() => setShowAudit(s => !s)}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className="ref-audit-pulse-dot" />
            <span style={{ fontWeight: 600 }}>FORCE STATUS & ACTIVITY LOG</span>
          </div>
          <span style={{ fontSize: 11 }}>{showAuditFeed ? '▲' : '▼'}</span>
        </button>

        {showAuditFeed && (
          <div className="ref-audit-body">
            <div className="readiness-row">
              <span className="readiness-dot dot-live" />
              <span>Systems operational</span>
            </div>
            <div className="readiness-row">
              <span
                className={`readiness-dot${pendingGates.length > 0 ? ' dot-auth' : ''}`}
                style={{ background: pendingGates.length > 0 ? '#a78bfa' : '#484f58' }}
              />
              <span>
                {pendingGates.length > 0
                  ? `${pendingGates.length} gate(s) awaiting auth`
                  : 'No pending gates'}
              </span>
            </div>

            <div className="feed-scroll" ref={feedRef} style={{ maxHeight: 180 }}>
              {allEntries.length === 0 && (
                <div className="feed-empty">No events yet</div>
              )}
              {allEntries.map(entry => (
                <div
                  key={entry.id}
                  className={`feed-entry${entry.id === pulse ? ' feed-pulse' : ''}`}
                  style={{ borderLeft: `3px solid ${TIER_COLOR[entry.tier] || '#484f58'}` }}
                >
                  <span className="feed-ts">{entry.ts}</span>
                  <span className="feed-text">{entry.text}</span>
                  <span className="feed-hash">{auditHash(entry.raw)}</span>
                </div>
              ))}
            </div>

            <div className="audit-note" style={{ marginTop: 6 }}>
              Append-only · {allEntries.length} entries recorded
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function buildText(msg) {
  switch (msg.type) {
    case 'tier_change':          return `${msg.hex_id?.slice(0, 8)} → ${msg.tier} (risk ${msg.risk_score?.toFixed(0)})`;
    case 'alert_fired':          return `ALERT fired — ${msg.hex_id?.slice(0, 8)}`;
    case 'persist_declared':     return `PERSISTENT THREAT — ${msg.hex_id?.slice(0, 8)} (${msg.cycles} cycles)`;
    case 'gate_pending':         return `AUTH needed — ${msg.hex_id?.slice(0, 8)}`;
    case 'gate_approved':        return `AUTH approved — ${msg.hex_id?.slice(0, 8)} by ${msg.operator_id}`;
    case 'snapshot':             return `Snapshot loaded — ${msg.hexes?.length ?? '?'} hexes`;
    case 'telemetry_tick':       return `📡 IoT Stream — ${msg.stations || 4} nodes active (${msg.rain_mm || 0}mm/h)`;
    case 'sensor_status_changed':return `⚡ SENSOR ${msg.status?.toUpperCase()} — ${msg.status === 'offline' ? 'Fallback to Satellite/NWP' : 'Restored to Live Telemetry'}`;
    case 'region_onboarded':     return `📍 Pipeline Resolved — ${msg.region || msg.label} (${msg.hex_count} hexes)`;
    default:                     return msg.type;
  }
}
