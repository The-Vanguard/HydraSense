/**
 * LeftColumn.jsx — Institutional record / left column (Final.md §13.4)
 *
 * Contains:
 *  - Force/readiness status
 *  - Append-only timestamped message feed
 *  - Tier-coloured alert-activation record
 *  - Audit-hash strip (tamper-evidence)
 *
 * Motion rule (§13.6): genuine Red alert may pulse once. Nothing else
 * pulses without a real state change.
 */
import React, { useState, useEffect, useRef } from 'react';

const TIER_COLOR = {
  Green:  '#22c55e',
  Yellow: '#eab308',
  Orange: '#f97316',
  Red:    '#ef4444',
};

function timestamp() {
  return new Date().toLocaleTimeString('en-IN', { hour12: false });
}

function auditHash(entry) {
  // Lightweight deterministic hash for tamper-evidence display
  let h = 0;
  for (const ch of JSON.stringify(entry)) h = (Math.imul(31, h) + ch.charCodeAt(0)) | 0;
  return Math.abs(h).toString(16).padStart(8, '0');
}

export default function LeftColumn({ wsAlerts = [], pendingGates = [] }) {
  const [feed, setFeed]   = useState([]);
  const [pulse, setPulse] = useState(null);
  const feedRef           = useRef(null);

  const processedRef = useRef(new Set());

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

        // Pulse on Red or deliberate sensor failure (§13.6, §14.5)
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

  return (
    <aside className="left-column">
      {/* Force/readiness status */}
      <div className="left-section">
        <div className="left-section-title">FORCE STATUS</div>
        <div className="readiness-row">
          <span className="readiness-dot dot-live" />
          <span>Systems operational</span>
        </div>
        <div className="readiness-row">
          <span className={`readiness-dot${pendingGates.length > 0 ? ' dot-auth' : ''}`}
                style={{ background: pendingGates.length > 0 ? '#a78bfa' : '#484f58' }} />
          <span>
            {pendingGates.length > 0
              ? `${pendingGates.length} gate(s) awaiting auth`
              : 'No pending gates'}
          </span>
        </div>
      </div>

      {/* Append-only message feed */}
      <div className="left-section" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div className="left-section-title">ACTIVITY LOG</div>
        <div className="feed-scroll" ref={feedRef}>
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
      </div>

      {/* Audit strip */}
      <div className="left-section audit-strip">
        <div className="left-section-title">AUDIT</div>
        <div className="audit-note">
          Append-only · {allEntries.length} entries
        </div>
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
