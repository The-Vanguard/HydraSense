/**
 * WeatherWidget.jsx — floating card with the rainfall / soil inputs the selected hex was scored on.
 *
 * Shows only values the backend actually used (GET /risk/{hex} -> inputs).  A missing value is shown
 * as "—", never estimated.  Temperature and humidity are not fetched by the pipeline, so they are not
 * shown.
 */
import React, { useState } from 'react';

const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d));

export default function WeatherWidget({ inputs = null, source = null, timestamp = null }) {
  const [minimized, setMinimized] = useState(false);
  const r24 = inputs?.rainfall_24h;
  const label = r24 == null ? 'NO RAINFALL DATA' : r24 >= 64.5 ? 'HEAVY RAIN (24 h)' : r24 >= 2.5 ? 'RAIN (24 h)' : 'LITTLE OR NO RAIN (24 h)';
  const sat = inputs?.soil_saturation_ratio;

  return (
    <div className="weather-widget-container">
      <div className="weather-widget-bar">
        <div className="weather-bar-title">
          <span className="weather-bar-dot" />
          <span>SCORING INPUTS · SELECTED HEX</span>
        </div>
        <button className="weather-min-btn" onClick={() => setMinimized(m => !m)}
                title={minimized ? 'Expand' : 'Minimize'}>
          {minimized ? '+ Max' : '— Min'}
        </button>
      </div>

      {!minimized && (
        <div className="weather-widget-card">
          <div className="weather-condition-label">{label}</div>
          <div className="weather-hero-temp" style={{ fontSize: 34 }}>
            {fmt(r24)}<span className="weather-degree" style={{ fontSize: 14 }}> mm / 24 h</span>
          </div>
          <div className="weather-metrics-row" style={{ flexWrap: 'wrap', rowGap: 4 }}>
            <div className="weather-metric-item"><span>1 h {fmt(inputs?.rainfall_1h)}</span></div>
            <span className="weather-metric-divider">•</span>
            <div className="weather-metric-item"><span>6 h {fmt(inputs?.rainfall_6h)}</span></div>
            <span className="weather-metric-divider">•</span>
            <div className="weather-metric-item"><span>72 h {fmt(inputs?.rainfall_72h_antecedent)}</span></div>
          </div>
          <div className="weather-metrics-row">
            <div className="weather-metric-item">
              <span>Soil saturation {sat == null ? '—' : `${Math.round(sat * 100)}%`}</span>
            </div>
          </div>
          <div style={{ fontSize: 9, opacity: 0.7, marginTop: 4 }}>
            {inputs ? `source: ${source || 'unknown'}${timestamp ? ` · ${new Date(timestamp).toLocaleTimeString()}` : ''}`
                    : 'inputs appear after the next scoring cycle for this hex'}
          </div>
        </div>
      )}
    </div>
  );
}
