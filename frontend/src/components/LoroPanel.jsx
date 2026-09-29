/**
 * LoroPanel.jsx — LORO Validation Panel (Stage 6 / Final.md §16.3)
 *
 * Displays the Leave-One-Region-Out cross-validation results alongside
 * the existing LOEO panel. Shows per-region detection rates and C_cal
 * empirical calibration result.
 */
import React, { useState, useEffect } from 'react';
import { getLoroResults } from '../api/client';

const TIER_COLORS = {
  'wayanad-kl':      '#f97316',
  'idukki-kl':       '#22c55e',
  'nilgiris-tn':     '#a78bfa',
  'rudraprayag-uk':  '#38bdf8',
  'chamoli-uk':      '#60a5fa',
  'kullu-hp':        '#fb923c',
  'mangan-sk':       '#34d399',
  'darjeeling-wb':   '#f472b6',
  'ribhoi-ml':       '#fbbf24',
  'dhemaji-as':      '#94a3b8',
};

function DetectionBar({ rate, n }) {
  const pct = rate != null ? Math.round(rate * 100) : null;
  const color = pct == null ? '#30363d'
    : pct >= 90 ? '#22c55e'
    : pct >= 70 ? '#eab308'
    : '#ef4444';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{
        flex: 1, height: 5, background: '#21262d', borderRadius: 3, overflow: 'hidden',
      }}>
        {pct != null && (
          <div style={{
            width: `${pct}%`, height: '100%',
            background: color, borderRadius: 3,
            transition: 'width 0.5s ease',
          }} />
        )}
      </div>
      <span style={{ fontSize: 10, color, fontWeight: 700, minWidth: 36, textAlign: 'right' }}>
        {pct != null ? `${pct}%` : 'N/A'}
      </span>
      {n != null && <span style={{ fontSize: 9, color: '#8b949e' }}>({n} ev)</span>}
    </div>
  );
}

export default function LoroPanel() {
  const [data,    setData]    = useState(null);
  const [error,   setError]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [open,    setOpen]    = useState(false);

  useEffect(() => {
    getLoroResults()
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => { setError('LORO results not yet available. Run: python ml/validation/loro.py'); setLoading(false); });
  }, []);

  const summary = data?.summary;
  const regions = data?.per_region_results || [];

  return (
    <div className="panel">
      <div
        className="panel-title"
        style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between' }}
        onClick={() => setOpen((o) => !o)}
      >
        <span>LORO Validation — 10-Fold Regional</span>
        <span style={{ fontSize: 10, color: '#8b949e' }}>{open ? '▲' : '▼'} Final.md §16.3</span>
      </div>

      {loading && (
        <div style={{ fontSize: 11, color: '#8b949e', padding: '8px 0' }}>Loading…</div>
      )}
      {error && (
        <div style={{ fontSize: 11, color: '#8b949e', padding: '6px 0', lineHeight: 1.5 }}>{error}</div>
      )}

      {summary && (
        <>
          {data?.reliability_warning && (
            <div style={{
              fontSize: 10, lineHeight: 1.5, color: '#fca5a5', background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.35)', borderRadius: 4, padding: '6px 8px', marginBottom: 10,
            }}>
              <strong>Not evidence of skill. </strong>{data.reliability_warning}
            </div>
          )}

          {/* Aggregate metrics always visible */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            {[
              { label: data?.reliability_warning ? 'Detection (only)' : 'Detection', value: `${Math.round((summary.detection_rate_aggregate || 0) * 100)}%`, color: '#22c55e' },
              { label: 'FP Rate',   value: data?.reliability_warning ? 'not measured'
                  : (summary.false_positive_rate_aggregate != null
                      ? `${(summary.false_positive_rate_aggregate * 100).toFixed(1)}%` : 'N/A'), color: '#eab308' },
              { label: 'Events',   value: `${summary.loro_n_events_detected}/${summary.loro_n_events_total}`, color: '#60a5fa' },
              { label: 'C_cal',    value: data?.reliability_warning ? 'untrusted' : (summary.c_cal_calibration?.c_cal_empirical ?? '—'), color: '#a78bfa' },
            ].map(({ label, value, color }) => (
              <div key={label} style={{
                flex: '1 0 80px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid #21262d',
                borderRadius: 6, padding: '6px 8px', textAlign: 'center',
              }}>
                <div style={{ fontSize: 15, fontWeight: 800, color }}>{value}</div>
                <div style={{ fontSize: 9, color: '#8b949e', marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>

          {/* C_cal note */}
          {summary.c_cal_calibration?.c_cal_note && (
            <div style={{
              fontSize: 10, color: '#8b949e', lineHeight: 1.5,
              background: 'rgba(167,139,250,0.05)',
              border: '1px solid rgba(167,139,250,0.15)',
              borderRadius: 4, padding: '6px 8px', marginBottom: 10,
            }}>
              <strong style={{ color: '#a78bfa' }}>C_cal: </strong>
              {summary.c_cal_calibration.c_cal_note}
            </div>
          )}

          {/* Per-region fold results (collapsible) */}
          {open && regions.length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 6, fontWeight: 600 }}>
                Per-Region Detection Rate (trained on 9, tested on 1)
              </div>
              {regions.map((r) => (
                <div key={r.region_code} style={{ marginBottom: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span style={{ fontSize: 10, color: TIER_COLORS[r.region_code] || '#e6edf3', fontWeight: 600 }}>
                      {r.region_label || r.region_code}
                    </span>
                    <span style={{ fontSize: 9, color: r.has_local_calibration ? '#22c55e' : '#8b949e' }}>
                      {r.has_local_calibration ? 'calibrated' : 'uncalibrated'}
                    </span>
                  </div>
                  <DetectionBar rate={r.detection_rate} n={r.n_events} />
                  {r.notes && (
                    <div style={{ fontSize: 9, color: '#8b949e', marginTop: 2, fontStyle: 'italic' }}>
                      {r.notes}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
