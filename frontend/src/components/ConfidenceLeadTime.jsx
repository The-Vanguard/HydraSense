/**
 * ConfidenceLeadTime.jsx — Phase 12
 * Displays confidence_score, lead_time_min (hour-granular), and lead_time_basis.
 * SRS §12 constraint: if lead_time_basis = "no_red_crossing_in_forecast_window",
 * show that exact honest string — never fabricate a number.
 */
import React from 'react';

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

export default function ConfidenceLeadTime({ risk }) {
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
    lead_time_min, lead_time_basis, factor_of_safety,
  } = risk;

  const tierColor     = TIER_COLOR[tier] || '#8b949e';
  const noForecast    = lead_time_basis === 'no_red_crossing_in_forecast_window';
  const leadFormatted = formatLeadTime(lead_time_min);

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
          <div className="lead-time-basis">
            no_red_crossing_in_forecast_window
          </div>
        ) : (
          <>
            <div className="lead-time-val">{leadFormatted ?? '—'}</div>
            <div className="lead-time-basis">{lead_time_basis}</div>
          </>
        )}
      </div>

      {/* Factor of safety */}
      {factor_of_safety != null && (
        <div style={{ marginTop: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
          <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 2 }}>Factor of safety (FS)</div>
          <div style={{
            fontSize: 18, fontWeight: 700,
            color: factor_of_safety < 1.0 ? '#ef4444' : factor_of_safety < 1.3 ? '#f97316' : '#22c55e',
          }}>
            {factor_of_safety.toFixed(2)}
          </div>
          {factor_of_safety < 1.0 && (
            <div style={{ fontSize: 10, color: '#ef4444', marginTop: 2 }}>
              FS &lt; 1.0 — slope instability indicated
            </div>
          )}
        </div>
      )}
    </div>
  );
}
