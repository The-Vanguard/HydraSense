/**
 * ConfidenceLeadTime.jsx — Phase 12
 * Displays confidence_score, lead_time_min (hour-granular), lead_time_basis,
 * the 24 h rainfall the score used, FS band gauge, and real-time lead-time countdown.
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


export default function ConfidenceLeadTime({ risk }) {
  const [countdown, setCountdown] = useState(null);
  const countdownRef = useRef(null);

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
    factor_of_safety_note,
  } = risk;

  const tierColor  = TIER_COLOR[tier] || '#8b949e';
  const noForecast = lead_time_basis === 'no_red_crossing_in_forecast_window';
  const leadFormatted = formatLeadTime(countdown);

  // FS band
  const fsMin = factor_of_safety_min ?? null;     // no band is invented when the engine gave none
  const fsMax = factor_of_safety_max ?? null;
  const fsVal = factor_of_safety;
  const fsBandVisible   = fsMin != null && fsMax != null;
  const fsBandStraddles = fsBandVisible && fsMin < 1.0 && fsMax >= 1.0;
  const fsColor = fsVal == null ? 'var(--mist)' : fsVal < 1.0 ? 'var(--danger)' : fsVal < 1.3 ? 'var(--orange)' : 'var(--success)';

  const rain24 = risk?.inputs?.rainfall_24h;

  return (
    <div className="panel">
      <div className="panel-title">Risk Score &amp; Confidence</div>

      {/* Risk score hero — bold, tier-colored, Inter Tight */}
      <div style={{
        background: `linear-gradient(135deg, ${tierColor}12 0%, ${tierColor}06 100%)`,
        border: `1px solid ${tierColor}30`,
        borderRadius: 'var(--r-inner)',
        padding: '12px 14px',
        marginBottom: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 8 }}>
          <span style={{
            fontFamily: 'var(--font-display)',
            fontSize: 48,
            fontWeight: 800,
            color: tierColor,
            lineHeight: 1,
            letterSpacing: '-0.03em',
          }}>
            {risk_score}
          </span>
          <span style={{ fontSize: 14, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>/ 100</span>
        </div>
        <span className={`tier-badge ${tier}`}>
          <span className="pulse-dot" />
          {tier}
        </span>
      </div>

      {/* 24 h rainfall the score used (from the backend; '—' if not available) */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 10, padding: '6px 10px',
        background: 'var(--sky)', borderRadius: 'var(--r-sm)',
        border: '1px solid var(--edge)',
      }}>
        <span style={{ fontSize: 10, color: 'var(--mist)', fontFamily: 'var(--font-mono)' }}>24h Rainfall</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)', fontVariantNumeric: 'tabular-nums', fontFamily: 'var(--font-mono)' }}>
          {rain24 == null ? '—' : `${Number(rain24).toFixed(1)} mm`}
        </span>
      </div>

      {/* Confidence bar */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11 }}>
          <span style={{ color: 'var(--text-muted)' }}>Confidence</span>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{confidence_score}%</span>
        </div>
        <div className="confidence-bar-wrap">
          <div className="confidence-bar-fill" style={{ width: `${confidence_score}%` }} />
        </div>
      </div>

      {/* Lead time */}
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 10 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Lead time (Red crossing)</div>
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
        <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 11 }}>
            <span style={{ color: 'var(--text-muted)' }}>Factor of safety (FS)</span>
            <span style={{ fontWeight: 700, color: fsColor, fontFamily: 'var(--font-mono)' }}>{fsVal.toFixed(2)}</span>
          </div>

          {fsBandVisible && (
            <div style={{ position: 'relative', height: 14, borderRadius: 'var(--r-xs)', background: 'var(--bg-card)', border: '1px solid var(--border)', overflow: 'hidden', marginBottom: 4 }}>
              {/* Failure threshold marker at FS=1.0 */}
              <div style={{ position: 'absolute', left: `${(1.0 / 3) * 100}%`, top: 0, bottom: 0, width: 1, background: 'rgba(239,68,68,0.5)' }} />
              {/* Uncertainty band */}
              <div style={{
                position: 'absolute',
                left: `${Math.min(100, (Math.max(0, fsMin) / 3) * 100)}%`,
                width: `${Math.min(100, ((Math.min(3, fsMax) - Math.max(0, fsMin)) / 3) * 100)}%`,
                top: 2, bottom: 2,
                background: fsBandStraddles ? 'rgba(239,68,68,0.35)' : 'rgba(16,185,129,0.25)',
                borderRadius: 3, transition: 'all 0.5s ease',
              }} />
              {/* Current FS value dot */}
              <div style={{
                position: 'absolute',
                left: `${Math.min(98, Math.max(2, (Math.min(3, fsVal) / 3) * 100))}%`,
                top: '50%', transform: 'translate(-50%,-50%)',
                width: 8, height: 8, borderRadius: '50%',
                background: fsColor, border: '2px solid var(--bg-card)',
              }} />
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-muted)' }}>
            {fsBandVisible && <span>Band: {fsMin.toFixed(2)} – {fsMax.toFixed(2)}</span>}
            {fsBandStraddles && <span style={{ color: 'var(--tier-red)' }}>straddles failure threshold</span>}
            {fsVal < 1.0 && !fsBandStraddles && <span style={{ color: 'var(--tier-red)' }}>FS &lt; 1.0 — instability</span>}
          </div>
        </div>
      )}

      {/* fsVal null but the real backend told us why (e.g. this hex has no
          real terrain data yet) -- disclose it instead of just going quiet. */}
      {fsVal == null && factor_of_safety_note && (
        <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8, fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.4 }}>
          Factor of safety (FS): {factor_of_safety_note}
        </div>
      )}
    </div>
  );
}
