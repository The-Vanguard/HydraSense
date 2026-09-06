/**
 * ValidationPanel.jsx — Phase 12
 * Static "How we validated this" panel.
 * Reads GET /validation/loeo ONCE on mount — no polling.
 * SRS §11: present as offline validation results, not live.
 */
import React, { useEffect, useState } from 'react';
import { getLoeoResults } from '../api/client';

function Stat({ label, value, dim }) {
  return (
    <div className="loeo-stat">
      <span style={{ color: '#8b949e' }}>{label}</span>
      <span className="loeo-val" style={dim ? { color: '#484f58' } : {}}>
        {value ?? '—'}
      </span>
    </div>
  );
}

export default function ValidationPanel() {
  const [loeo, setLoeo]   = useState(null);
  const [error, setError] = useState(null);

  // Fetch once on mount — never re-poll (SRS §11 requirement)
  useEffect(() => {
    getLoeoResults()
      .then(setLoeo)
      .catch(() => setError('Could not load LOEO results'));
  }, []);

  return (
    <div className="panel">
      <div className="panel-title">
        LOEO Validation
        <span style={{ marginLeft: 6, fontSize: 9, color: '#484f58', textTransform: 'none', fontWeight: 400 }}>
          — offline, not live
        </span>
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 11 }}>{error}</div>}

      {!loeo && !error && (
        <div className="empty-state">Loading…</div>
      )}

      {loeo && (
        <>
          <Stat label="Events evaluated (N)"  value={loeo.loeo_n_events} />
          <Stat label="Events detected"       value={loeo.loeo_n_detected} />
          <Stat
            label="Detection rate"
            value={loeo.detection_rate != null
              ? `${(loeo.detection_rate * 100).toFixed(1)}%`
              : '—'}
          />
          <Stat
            label="False-positive rate"
            value={loeo.false_positive_rate != null
              ? `${(loeo.false_positive_rate * 100).toFixed(1)}%`
              : 'N/A'}
            dim={loeo.false_positive_rate == null}
          />
          <Stat
            label="Timing error (mean)"
            value={loeo.timing_error?.mean_min != null
              ? `${loeo.timing_error.mean_min} min`
              : 'N/A'}
            dim={loeo.timing_error?.mean_min == null}
          />
          <Stat
            label="Timing error (median)"
            value={loeo.timing_error?.median_min != null
              ? `${loeo.timing_error.median_min} min`
              : 'N/A'}
            dim={loeo.timing_error?.median_min == null}
          />
          <Stat label="Leakage buffer"       value={`${loeo.leakage_buffer_days} days`} />
          <Stat label="Detection threshold"  value={loeo.detection_threshold} />

          {loeo.data_completeness_note && (
            <div style={{
              marginTop: 8, padding: '6px 8px',
              background: 'rgba(88,166,255,0.07)',
              border: '1px solid rgba(88,166,255,0.2)',
              borderRadius: 6, fontSize: 10, color: '#8b949e', lineHeight: 1.5,
            }}>
              ℹ {loeo.data_completeness_note}
            </div>
          )}
        </>
      )}
    </div>
  );
}
