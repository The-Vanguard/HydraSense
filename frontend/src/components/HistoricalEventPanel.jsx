/**
 * HistoricalEventPanel.jsx — Phase 13
 * Sidebar detail panel for a real, sourced historical-event pin (multiregion
 * dataset). Deliberately does NOT show a risk_score/tier — that would imply
 * a live model output, which this data is not (CLAUDE.md labeling rule).
 */
import React from 'react';

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

export default function HistoricalEventPanel({ selectedEvent, onClose }) {
  if (!selectedEvent) return null;

  const { region, lat, lon, events } = selectedEvent;
  const listed = events.slice(0, MAX_LISTED);
  const remaining = events.length - listed.length;

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

      <div style={{ maxHeight: 260, overflowY: 'auto' }}>
        {listed.map((ev) => (
          <div
            key={ev.event_id}
            style={{
              borderLeft: `3px solid ${TYPE_COLORS[ev.type] || TYPE_COLORS.unknown}`,
              paddingLeft: 8, marginBottom: 8, fontSize: 11,
            }}
          >
            <div style={{ color: '#e6edf3', fontWeight: 600 }}>{ev.date || 'date unknown'}</div>
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
