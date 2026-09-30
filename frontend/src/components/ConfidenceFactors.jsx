/**
 * ConfidenceFactors.jsx — v2 Sec. 9.2 / 13.3 four-factor confidence for the selected hex.
 * Shows each factor as a bar, the one-line primary reason, and the backend's stated assumptions.
 * The score is an uncertainty/coverage indicator, not a probability of being right.
 */
import React, { useEffect, useState } from 'react';
import { getConfidenceFactors } from '../api/client';

const LABELS = {
  model_probability:  'Model probability',
  engine_uncertainty: 'Engine (FS band)',
  calibration:        'Local calibration',
  input_coverage:     'Input coverage',
};

export default function ConfidenceFactors({ hexId }) {
  const [data, setData] = useState(null);
  const [err, setErr]   = useState(null);

  useEffect(() => {
    setData(null); setErr(null);
    if (!hexId) return;
    getConfidenceFactors(hexId).then(setData)
      .catch((e) => setErr(e?.response?.data?.detail || 'not available'));
  }, [hexId]);

  if (!hexId) return null;
  return (
    <div className="panel">
      <div className="panel-title">Confidence — why</div>
      {err && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Confidence breakdown {err}.</div>}
      {data && (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
            <span className="metric-value">{Math.round(data.confidence_score)}</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>/ 100 · {data.confidence_short_word}</span>
          </div>
          <div style={{ fontSize: 11, marginBottom: 8 }}>
            Main reason: <strong>{data.primary_reason}</strong>
          </div>
          {Object.entries(data.confidence_factors || {}).map(([k, v]) => (
            <div key={k} style={{ marginBottom: 5 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)' }}>
                <span>{LABELS[k] || k}</span><span style={{ fontFamily: 'var(--font-mono)' }}>{v}</span>
              </div>
              <div className="confidence-bar-wrap">
                <div className="confidence-bar" style={{ width: `${Math.max(0, Math.min(100, v))}%` }} />
              </div>
            </div>
          ))}
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.4 }}>
            {data.label}. Constants are provisional
            {data.assumptions?.length ? `; assumptions: ${data.assumptions.join('; ')}` : ''}.
          </div>
        </>
      )}
    </div>
  );
}
