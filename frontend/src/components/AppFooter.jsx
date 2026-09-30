/**
 * AppFooter.jsx — Agency-connection dots strip (Final.md §13.4)
 *
 * Shows per-source health dots for every data layer this region's pipeline
 * actually uses. Quiet when healthy, draws the eye only on fault.
 * Makes the multi-source-fusion claim (§5, item 2) literal and visible.
 */
import React from 'react';

// Layers the pipeline actually uses.  Static layers are fetched once at onboarding (GeoPackage).
const SOURCES = [
  { key: 'dem',       label: 'DEM',           agency: 'OpenTopography SRTM (onboarding)', fixed: 'static' },
  { key: 'landcover', label: 'Land cover',    agency: 'ESA WorldCover (onboarding)',      fixed: 'static' },
  { key: 'soil',      label: 'Soil',          agency: 'SoilGrids (onboarding)',           fixed: 'static' },
  { key: 'rainfall',  label: 'Rainfall',      agency: 'IMERG / Open-Meteo (live chain)' },
  { key: 'sensors',   label: 'Sensors',       agency: 'none deployed',                    fixed: 'none' },
];

// Map a backend data_source label to a display status.
function normalise(v) {
  if (!v) return 'unknown';
  if (/live/.test(v)) return 'live';
  if (/cached|demo/.test(v)) return 'cached';
  if (v === 'sensor') return 'simulated';
  return STATUS_COLOR[v] ? v : 'unknown';
}

const STATUS_COLOR = {
  live:     '#22c55e',
  cached:   '#eab308',
  fallback: '#f97316',
  offline:  '#ef4444',
  unknown:  '#484f58',
  static:   '#60a5fa',
  simulated:'#a855f7',
  none:     '#484f58',
};

const STATUS_LABEL = {
  live:     'LIVE',
  cached:   'CACHED',
  fallback: 'FALLBACK',
  offline:  'OFFLINE',
  unknown:  '—',
  static:   'STATIC',
  simulated:'SIMULATED',
  none:     'NONE',
};

export default function AppFooter({ dataSources = {}, frozenDate = null }) {
  return (
    <footer className="app-footer">
      {/* Agency connection dots */}
      <div className="footer-sources">
        {SOURCES.map(({ key, label, agency, fixed }) => {
          const status = fixed || normalise(dataSources[key]);
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
      <div className="footer-ref">HydraSense · SIH prototype · not an official warning service</div>
    </footer>
  );
}
