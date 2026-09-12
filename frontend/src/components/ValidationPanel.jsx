/**
 * ValidationPanel.jsx — HydraSense Validation Metrics
 * LOEO cross-validation benchmark stats.
 * Rows animate in one-by-one on first load.
 */
import React, { useEffect, useState } from 'react';
import { getLoeoResults } from '../api/client';

function Stat({ label, value, dim, visible }) {
  return (
    <div
      className="loeo-stat"
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(6px)',
        transition: 'opacity 0.35s ease, transform 0.35s ease',
      }}
    >
      <span style={{ color: '#8b949e' }}>{label}</span>
      <span className="loeo-val" style={dim ? { color: '#484f58' } : {}}>
        {value ?? '—'}
      </span>
    </div>
  );
}

// Every getter returns null (rendered as "—") when the real field is
// missing -- never a plausible-looking placeholder number. false_positive_rate
// is genuinely null in the real Phase 7 output (see false_positive_rate_note);
// showing a fake percentage there would misrepresent a disclosed limitation
// as a real result.
const STATS_DEF = [
  { key: 'n_events',     label: 'Events evaluated (N)',   getter: c => c.loeo_n_events ?? null },
  { key: 'n_detected',   label: 'Events detected',        getter: c => c.loeo_n_detected ?? null },
  { key: 'det_rate',     label: 'Detection rate',         getter: c => c.detection_rate != null ? `${(c.detection_rate*100).toFixed(1)}%` : null },
  { key: 'fp_rate',      label: 'False-positive rate',    getter: c => c.false_positive_rate != null ? `${(c.false_positive_rate*100).toFixed(1)}%` : (c.false_positive_rate_note ? 'Not computed' : null) },
  { key: 'lt_mean',      label: 'Timing error (mean)',    getter: c => c.timing_error?.mean_min != null ? `${(c.timing_error.mean_min/60).toFixed(1)}h (${c.timing_error.mean_min} min)` : null },
  { key: 'lt_median',    label: 'Timing error (median)',  getter: c => c.timing_error?.median_min != null ? `${(c.timing_error.median_min/60).toFixed(1)}h (${c.timing_error.median_min} min)` : null },
  { key: 'leakage',      label: 'Leakage buffer',         getter: c => c.leakage_buffer_days != null ? `${c.leakage_buffer_days} days` : null },
];

export default function ValidationPanel() {
  const [apiLoeo,    setApiLoeo]    = useState(null);
  const [error,      setError]      = useState(null);
  const [visibleN,   setVisibleN]   = useState(0); // how many rows revealed so far

  useEffect(() => {
    getLoeoResults().then(setApiLoeo).catch(() => setError('Could not load validation results'));
  }, []);

  const current = apiLoeo?.summary;

  // Animate rows in one-by-one whenever current data changes
  useEffect(() => {
    if (!current) return;
    setVisibleN(0);
    STATS_DEF.forEach((_, i) => {
      setTimeout(() => setVisibleN(n => Math.max(n, i + 1)), i * 110 + 120);
    });
  }, [current]);

  return (
    <div className="panel">
      <div className="panel-title">
        LOEO Validation
        <span style={{ marginLeft: 6, fontSize: 9, color: '#8b949e', textTransform: 'none', fontWeight: 400 }}>
          — model benchmark
        </span>
      </div>

      {error && !current && <div style={{ color: '#ef4444', fontSize: 11 }}>{error}</div>}
      {!current && !error && <div className="empty-state">Loading…</div>}

      {current && STATS_DEF.map((s, i) => (
        <Stat
          key={s.key}
          label={s.label}
          value={s.getter(current)}
          visible={visibleN > i}
        />
      ))}

      {current?.data_completeness_note && (
        <div style={{ fontSize: 9, color: '#6e7681', marginTop: 8, paddingTop: 8, borderTop: '1px solid #30363d', lineHeight: 1.4 }}>
          {current.data_completeness_note}
        </div>
      )}
    </div>
  );
}
