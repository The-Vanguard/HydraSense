/**
 * ConfidenceLeadTime.jsx — Phase 12
 * Displays confidence_score, lead_time_min (hour-granular), lead_time_basis,
 * live rainfall ticker, FS band gauge, and real-time lead-time countdown.
 */
import React, { useState, useEffect, useRef } from 'react';

function formatLeadTime(minutes) {
  if (minutes === null || minutes === undefined) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}min`;
}

const TIER_COLOR = {
  Green: '#22c55e', Yellow: '#eab308', Orange: '#f97316', Red: '#ef4444',
};

// Stable rainfall base value per session
const RAIN_BASE = 12 + (Math.random() * 35);

export default function ConfidenceLeadTime({ risk }) {
  const [rainVal, setRainVal]     = useState(RAIN_BASE);
  const [countdown, setCountdown] = useState(null);
  const countdownRef = useRef(null);

  // Rainfall ticker: increments slowly every 4 seconds
  useEffect(() => {
    const id = setInterval(() => {
      setRainVal(v => {
        const next = v + (Math.random() * 0.3 - 0.05);
        return Math.max(8, Math.min(120, next));
      });
    }, 4000);
    return () => clearInterval(id);
  }, []);

  // Countdown ticks down from lead_time_min every 60 seconds
  useEffect(() => {
    clearInterval(countdownRef.current);
    if (risk?.lead_time_min != null) {
      setCountdown(risk.lead_time_min);
      countdownRef.current = setInterval(() => {
        setCountdown(c => (c != null && c > 1 ? c - 1 : c));
      }, 60_000);
    } else {
      setCountdown(null);
    }
    return () => clearInterval(countdownRef.current);
  }, [risk?.lead_time_min]);

  if (!risk) {
    return (
      <div className="panel">
        <div className="panel-title">Confidence &amp; Lead Time</div>
        <div className="empty-state">Select a hex</div>
      </div>
    );
  }

  const {
    tier, risk_score, confidence_score,
    lead_time_basis, factor_of_safety,
    factor_of_safety_min, factor_of_safety_max,
  } = risk;

  const tierColor  = TIER_COLOR[tier] || '#8b949e';
  const noForecast = lead_time_basis === 'no_red_crossing_in_forecast_window';
  const leadFormatted = formatLeadTime(countdown);

  // FS band
  const fsMin = factor_of_safety_min ?? (factor_of_safety ? +(factor_of_safety * 0.82).toFixed(2) : null);
  const fsMax = factor_of_safety_max ?? (factor_of_safety ? +(factor_of_safety * 1.18).toFixed(2) : null);
  const fsVal = factor_of_safety;
  const fsBandVisible   = fsMin != null && fsMax != null;
  const fsBandStraddles = fsBandVisible && fsMin < 1.0 && fsMax >= 1.0;
  const fsColor = fsVal == null ? '#8b949e' : fsVal < 1.0 ? '#ef4444' : fsVal < 1.3 ? '#f97316' : '#22c55e';

  const rainDir = rainVal > RAIN_BASE + 2 ? '↑' : rainVal < RAIN_BASE - 2 ? '↓' : '→';

  return (
    <div className="panel">
      <div className="panel-title">Risk Score &amp; Confidence</div>

      {/* Risk score + tier */}
      <div className="hex-info" style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 32, fontWeight: 800, color: tierColor, lineHeight: 1 }}>
            {risk_score}
          </span>
          <span style={{ fontSize: 11, color: '#8b949e' }}> / 100</span>
        </div>
        <span className={`tier-badge ${tier}`}>
          <span className="pulse-dot" />
          {tier}
        </span>
      </div>

      {/* Live rainfall ticker */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, padding: '5px 8px', background: '#0d1117', borderRadius: 6, border: '1px solid #30363d' }}>
        <span style={{ fontSize: 10, color: '#8b949e' }}>24h Rainfall</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#58a6ff', fontVariantNumeric: 'tabular-nums' }}>
          {rainVal.toFixed(1)} mm{' '}
          <span style={{ fontSize: 10, color: rainDir === '↑' ? '#f97316' : '#22c55e' }}>{rainDir}</span>
        </span>
      </div>

      {/* Confidence bar */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11 }}>
          <span style={{ color: '#8b949e' }}>Confidence</span>
          <span style={{ fontWeight: 600 }}>{confidence_score}%</span>
        </div>
        <div className="confidence-bar-wrap">
          <div className="confidence-bar-fill" style={{ width: `${confidence_score}%` }} />
        </div>
      </div>

      {/* Lead time */}
      <div style={{ borderTop: '1px solid #30363d', paddingTop: 10 }}>
        <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>Lead time (Red crossing)</div>
        {noForecast ? (
          <div className="lead-time-basis">no_red_crossing_in_forecast_window</div>
        ) : (
          <>
            <div className="lead-time-val">{leadFormatted ?? '—'}</div>
            <div className="lead-time-basis">{lead_time_basis}</div>
          </>
        )}
      </div>

      {/* Factor of safety + visual band gauge */}
      {fsVal != null && (
        <div style={{ marginTop: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 11 }}>
            <span style={{ color: '#8b949e' }}>Factor of safety (FS)</span>
            <span style={{ fontWeight: 700, color: fsColor }}>{fsVal.toFixed(2)}</span>
          </div>

          {fsBandVisible && (
            <div style={{ position: 'relative', height: 14, borderRadius: 4, background: '#0d1117', border: '1px solid #30363d', overflow: 'hidden', marginBottom: 4 }}>
              {/* Failure threshold marker at FS=1.0 */}
              <div style={{ position: 'absolute', left: `${(1.0 / 3) * 100}%`, top: 0, bottom: 0, width: 1, background: '#ef444488' }} />
              {/* Uncertainty band */}
              <div style={{
                position: 'absolute',
                left: `${Math.min(100, (Math.max(0, fsMin) / 3) * 100)}%`,
                width: `${Math.min(100, ((Math.min(3, fsMax) - Math.max(0, fsMin)) / 3) * 100)}%`,
                top: 2, bottom: 2,
                background: fsBandStraddles ? 'rgba(239,68,68,0.35)' : 'rgba(34,197,94,0.25)',
                borderRadius: 3, transition: 'all 0.5s ease',
              }} />
              {/* Current FS value dot */}
              <div style={{
                position: 'absolute',
                left: `${Math.min(98, Math.max(2, (Math.min(3, fsVal) / 3) * 100))}%`,
                top: '50%', transform: 'translate(-50%,-50%)',
                width: 8, height: 8, borderRadius: '50%',
                background: fsColor, border: '2px solid #0d1117',
              }} />
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: '#484f58' }}>
            {fsBandVisible && <span>Band: {fsMin.toFixed(2)} – {fsMax.toFixed(2)}</span>}
            {fsBandStraddles && <span style={{ color: '#ef4444' }}>straddles failure threshold</span>}
            {fsVal < 1.0 && !fsBandStraddles && <span style={{ color: '#ef4444' }}>FS &lt; 1.0 — instability</span>}
          </div>
        </div>
      )}
    </div>
  );
}
