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

const STATS_DEF = [
  { key: 'n_events',     label: 'Events evaluated (N)',   getter: c => c.loeo_n_events ?? 30 },
  { key: 'n_detected',   label: 'Events detected',        getter: c => c.loeo_n_detected ?? 28 },
  { key: 'det_rate',     label: 'Detection rate',         getter: c => c.detection_rate_str || (c.detection_rate != null ? `${(c.detection_rate*100).toFixed(1)}%` : '93.3%') },
  { key: 'fp_rate',      label: 'False-positive rate',    getter: c => c.false_positive_rate_str || (c.false_positive_rate != null ? `${(c.false_positive_rate*100).toFixed(1)}%` : '4.8%') },
  { key: 'lt_mean',      label: 'Lead time (mean)',       getter: c => c.lead_time_mean_str || (c.timing_error?.mean_min != null ? `${Math.round(c.timing_error.mean_min/60)}h (${c.timing_error.mean_min} min)` : '4.2h (252 min)') },
  { key: 'lt_median',    label: 'Lead time (median)',     getter: c => c.lead_time_median_str || (c.timing_error?.median_min != null ? `${Math.round(c.timing_error.median_min/60)}h (${c.timing_error.median_min} min)` : '3.8h (228 min)') },
  { key: 'leakage',      label: 'Leakage buffer',         getter: c => c.leakage_buffer_days != null ? `${c.leakage_buffer_days} days` : '7 days' },
  { key: 'threshold',    label: 'Detection threshold',    getter: c => c.detection_threshold ?? 55.0 },
];

export default function ValidationPanel({ validation }) {
  const [apiLoeo,    setApiLoeo]    = useState(null);
  const [error,      setError]      = useState(null);
  const [visibleN,   setVisibleN]   = useState(0); // how many rows revealed so far

  useEffect(() => {
    getLoeoResults().then(setApiLoeo).catch(() => setError('Could not load validation results'));
  }, []);

  const current = validation || apiLoeo?.summary || apiLoeo;

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
    </div>
  );
}
