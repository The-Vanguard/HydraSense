/**
 * AppFooter.jsx — Agency-connection dots strip (Final.md §13.4)
 *
 * Shows per-source health dots for every data layer this region's pipeline
 * actually uses. Quiet when healthy, draws the eye only on fault.
 * Makes the multi-source-fusion claim (§5, item 2) literal and visible.
 */
import React from 'react';

const SOURCES = [
  { key: 'dem',      label: 'DEM',       agency: 'OpenTopography' },
  { key: 'landcover',label: 'Land Cover', agency: 'ESA WorldCover' },
  { key: 'soil',     label: 'Soil',       agency: 'SoilGrids' },
  { key: 'rainfall', label: 'Rainfall',   agency: 'Open-Meteo' },
  { key: 'era5',     label: 'ERA5',       agency: 'Copernicus' },
  { key: 'smap',     label: 'SMAP',       agency: 'NASA' },
  { key: 'iot',      label: 'IoT',        agency: 'MQTT Sensor' },
];

const STATUS_COLOR = {
  live:     '#22c55e',
  cached:   '#eab308',
  fallback: '#f97316',
  offline:  '#ef4444',
  unknown:  '#484f58',
};

const STATUS_LABEL = {
  live:     'LIVE',
  cached:   'CACHED',
  fallback: 'FALLBACK',
  offline:  'OFFLINE',
  unknown:  '—',
};

export default function AppFooter({ dataSources = {}, frozenDate = null }) {
  return (
    <footer className="app-footer">
      {/* Agency connection dots */}
      <div className="footer-sources">
        {SOURCES.map(({ key, label, agency }) => {
          const status = dataSources[key] || 'unknown';
          const color  = STATUS_COLOR[status] || STATUS_COLOR.unknown;
          return (
            <div key={key} className="footer-source-dot" title={`${agency}: ${STATUS_LABEL[status]}`}>
              <span
                className={`source-dot${status === 'live' ? ' dot-live' : ''}`}
                style={{ background: color }}
              />
              <span className="source-label">{label}</span>
              {status !== 'live' && status !== 'unknown' && (
                <span className="source-status-badge" style={{ color }}>
                  {STATUS_LABEL[status]}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Validation frozen date (§13.4 §16.6) */}
      <div className="footer-validation-note">
        {frozenDate
          ? `validation frozen: ${frozenDate}`
          : 'validation frozen: LORO + LOEO (run Stage 4)'}
      </div>

      {/* HydraSense_Final.md reference */}
      <div className="footer-ref">HydraSense_Final.md · §15.5</div>
    </footer>
  );
}
