/**
 * HistoricalEventPanel.jsx — Phase 13
 * Sidebar detail panel for a real, sourced historical-event pin (multiregion
 * dataset). Per-event tabpfn_risk_score/tier (Step 6a, run once explicitly)
 * is a REAL model output for that event's actual at-disaster conditions --
 * NOT a live/current score. Its caveat must always render alongside it
 * (CLAUDE.md labeling rule: never hide a known limitation).
 */
import React from 'react';

const TIER_COLORS = {
  Green: '#22c55e', Yellow: '#eab308', Orange: '#f97316', Red: '#ef4444',
};

const TYPE_LABELS = {
  flash_flood:    'Flash flood',
  riverine_flood: 'Riverine flood',
  landslide_only: 'Landslide',
  ambiguous:      'Ambiguous cause',
  unknown:        'Unknown cause',
};

const TYPE_COLORS = {
  flash_flood:    '#38bdf8',
  riverine_flood: '#818cf8',
  landslide_only: '#a78bfa',
  ambiguous:      '#94a3b8',
  unknown:        '#64748b',
};

const MAX_LISTED = 15;

// Real SRTM30m+pysheds terrain fields (data/multiregion/events/terrain_features_points.json)
// -- label + unit only, no computed/derived risk value.
const TERRAIN_FIELDS = [
  ['elevation',                     'Elevation',            'm'],
  ['slope_deg',                     'Slope',                '°'],
  ['aspect',                        'Aspect',                '°'],
  ['TWI',                           'Topographic wetness index', ''],
  ['TRI',                           'Terrain roughness index',   ''],
  ['distance_to_river_m',           'Distance to river',    'm'],
  ['flow_accumulation_cells',       'Flow accumulation',    'cells'],
  ['drainage_density_km_per_km2',   'Drainage density',     'km/km²'],
  ['cwc_danger_level_m',            'CWC danger level',     'm'],
];

export default function HistoricalEventPanel({ selectedEvent, onClose }) {
  if (!selectedEvent) return null;

  const { region, lat, lon, events, staticFeatures } = selectedEvent;
  const listed = events.slice(0, MAX_LISTED);
  const remaining = events.length - listed.length;
  const terrainRows = TERRAIN_FIELDS
    .map(([key, label, unit]) => [key, label, unit, staticFeatures?.[key]])
    .filter(([, , , v]) => v !== null && v !== undefined);
  const anyTabpfn = events.find((ev) => ev.tabpfn_risk_score != null);

  return (
    <div className="panel" style={{ borderColor: '#38bdf8' }}>
      <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>📌 {region}</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: '#8b949e',
            cursor: 'pointer', fontSize: 14, padding: 0,
          }}
          title="Back to live view"
        >
          ✕
        </button>
      </div>

      <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>
        {lat?.toFixed(4)}° N, {lon?.toFixed(4)}° E
      </div>

      <div style={{
        display: 'inline-block', fontSize: 10, fontWeight: 700,
        color: '#38bdf8', border: '1px solid #38bdf8', borderRadius: 4,
        padding: '2px 6px', marginBottom: 8,
      }}>
        SOURCED HISTORICAL DATA — NOT A LIVE MODEL OUTPUT
      </div>

      <div style={{ fontSize: 12, color: '#e6edf3', marginBottom: 8 }}>
        <strong>{events.length}</strong> real recorded event{events.length === 1 ? '' : 's'}
        {' '}(India Flood Inventory v3, IMD-sourced)
      </div>

      {anyTabpfn && (
        <div style={{
          marginBottom: 10, fontSize: 10, color: '#fbbf24',
          border: '1px solid #92640a', background: 'rgba(146,100,10,0.12)',
          borderRadius: 4, padding: '6px 8px', lineHeight: 1.4,
        }}>
          ⚠ {anyTabpfn.tabpfn_caveat}
        </div>
      )}

      {terrainRows.length > 0 && (
        <div style={{ marginBottom: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4, letterSpacing: 0.5 }}>
            TERRAIN PROFILE (real, SRTM 30m + pysheds)
          </div>
          {terrainRows.map(([key, label, unit, v]) => (
            <div key={key} style={{
              display: 'flex', justifyContent: 'space-between',
              fontSize: 11, padding: '2px 0', color: '#c9d1d9',
            }}>
              <span>{label}</span>
              <span style={{ fontWeight: 600 }}>
                {typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v}{unit ? ` ${unit}` : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      <div style={{ maxHeight: 220, overflowY: 'auto' }}>
        {listed.map((ev) => (
          <div
            key={ev.event_id}
            style={{
              borderLeft: `3px solid ${TYPE_COLORS[ev.type] || TYPE_COLORS.unknown}`,
              paddingLeft: 8, marginBottom: 8, fontSize: 11,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ color: '#e6edf3', fontWeight: 600 }}>{ev.date || 'date unknown'}</div>
              {ev.tabpfn_risk_score != null && (
                <span style={{
                  fontSize: 10, fontWeight: 700, borderRadius: 3, padding: '1px 5px',
                  color: TIER_COLORS[ev.tabpfn_tier] || '#8b949e',
                  border: `1px solid ${TIER_COLORS[ev.tabpfn_tier] || '#8b949e'}`,
                }}>
                  TabPFN {ev.tabpfn_risk_score}/100 · {ev.tabpfn_tier}
                </span>
              )}
            </div>
            <div style={{ color: '#8b949e' }}>
              {TYPE_LABELS[ev.type] || ev.type || 'unknown'}
              {ev.severity ? ` · ${ev.severity}` : ''}
            </div>
            <div style={{ color: '#6e7681', fontSize: 10 }}>{ev.source}</div>
          </div>
        ))}
        {remaining > 0 && (
          <div style={{ fontSize: 10, color: '#8b949e', fontStyle: 'italic' }}>
            + {remaining} more real event{remaining === 1 ? '' : 's'} not shown
          </div>
        )}
      </div>
    </div>
  );
}
