/**
 * HistoricalEventPanel.jsx — Phase 13
 * Sidebar detail panel for a real, sourced historical-event pin (multiregion
 * dataset). Per-event tabpfn_risk_score/tier (Step 6a, run once explicitly)
 * is a REAL model output for that event's actual at-disaster conditions --
 * NOT a live/current score. Its caveat must always render alongside it
 * (CLAUDE.md labeling rule: never hide a known limitation).
 */
import React, { useEffect, useState } from 'react';
import { getTabpfnImportance } from '../api/client';

const TIER_COLORS = {
  Green: '#22c55e', Yellow: '#eab308', Orange: '#f97316', Red: '#ef4444',
};

const TYPE_LABELS = {
  flash_flood:    'Flash flood',
  riverine_flood: 'Riverine flood',
  landslide_only: 'Landslide',
  ambiguous:      'Ambiguous cause',
  unknown:        'Unknown cause',
};

const TYPE_COLORS = {
  flash_flood:    '#38bdf8',
  riverine_flood: '#818cf8',
  landslide_only: '#a78bfa',
  ambiguous:      '#94a3b8',
  unknown:        '#64748b',
};

const MAX_LISTED = 15;

// Real dataset date format is "DD-MM-YYYY HH:mm" (India Flood Inventory v3) --
// plain Date.parse misreads this as MM-DD, so events sort wrong chronologically
// unless parsed explicitly here.
function parseEventDate(d) {
  if (!d) return null;
  const m = /^(\d{1,2})-(\d{1,2})-(\d{4})/.exec(d);
  if (m) return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
  const t = Date.parse(d);
  return Number.isNaN(t) ? null : new Date(t);
}

const FEATURE_LABELS = {
  elevation: 'Elevation', slope_deg: 'Slope', aspect: 'Aspect',
  TWI: 'Topographic wetness index', TRI: 'Terrain roughness index',
  distance_to_river_m: 'Distance to river', flow_accumulation_cells: 'Flow accumulation',
  drainage_density_km_per_km2: 'Drainage density', cwc_danger_level_m: 'CWC danger level',
  rainfall_1h: 'Rainfall (1h)', rainfall_3h: 'Rainfall (3h)', rainfall_6h: 'Rainfall (6h)',
  rainfall_24h: 'Rainfall (24h)', rainfall_72h_antecedent: 'Rainfall (72h antecedent)',
  antecedent_precipitation_index: 'Antecedent precipitation index',
  rain_intensity_mm_hr: 'Rain intensity', soil_saturation_ratio: 'Soil saturation ratio',
  river_water_level_m: 'River water level', river_level_change_m_per_hr: 'River level change rate',
};

// Simple inline SVG sparkline -- no charting library, real data only.
function TrendSparkline({ points }) {
  if (points.length < 2) return null;
  const W = 220, H = 56, PAD = 6;
  const xs = points.map((_, i) => PAD + (i * (W - 2 * PAD)) / (points.length - 1));
  const ys = points.map((p) => H - PAD - (p.score / 100) * (H - 2 * PAD));
  const path = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ');
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <path d={path} fill="none" stroke="#38bdf8" strokeWidth="2" />
      {xs.map((x, i) => (
        <circle key={i} cx={x} cy={ys[i]} r={3} fill={TIER_COLORS[points[i].tier] || '#38bdf8'} />
      ))}
    </svg>
  );
}

// Real Chronos-Bolt 1-day (hourly-step) river-level forecast, with its real
// low/high quantile band -- no fabricated smoothing, straight from
// data/multiregion/model_ready/chronos/predictions.json.
function RiverTrendChart({ median, low, high }) {
  if (!median || median.length < 2) return null;
  const W = 220, H = 64, PAD = 6;
  const all = [...median, ...(low || []), ...(high || [])];
  const min = Math.min(...all), max = Math.max(...all);
  const span = max - min || 1;
  const n = median.length;
  const x = (i) => PAD + (i * (W - 2 * PAD)) / (n - 1);
  const y = (v) => H - PAD - ((v - min) / span) * (H - 2 * PAD);
  const linePath = (vals) => vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  let bandPath = null;
  if (low && high && low.length === n && high.length === n) {
    const top = high.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const bottom = low.map((v, i) => `L${x(n - 1 - i).toFixed(1)},${y(low[n - 1 - i]).toFixed(1)}`).join(' ');
    bandPath = `${top} ${bottom} Z`;
  }
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      {bandPath && <path d={bandPath} fill="#38bdf8" opacity={0.15} stroke="none" />}
      <path d={linePath(median)} fill="none" stroke="#38bdf8" strokeWidth="2" />
    </svg>
  );
}

// Real SRTM30m+pysheds terrain fields (data/multiregion/events/terrain_features_points.json)
// -- label + unit only, no computed/derived risk value.
const TERRAIN_FIELDS = [
  ['elevation',                     'Elevation',            'm'],
  ['slope_deg',                     'Slope',                '°'],
  ['aspect',                        'Aspect',                '°'],
  ['TWI',                           'Topographic wetness index', ''],
  ['TRI',                           'Terrain roughness index',   ''],
  ['distance_to_river_m',           'Distance to river',    'm'],
  ['flow_accumulation_cells',       'Flow accumulation',    'cells'],
  ['drainage_density_km_per_km2',   'Drainage density',     'km/km²'],
  ['cwc_danger_level_m',            'CWC danger level',     'm'],
];

export default function HistoricalEventPanel({ selectedEvent, onClose }) {
  const [importance, setImportance] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getTabpfnImportance()
      .then((data) => { if (!cancelled && data?.features) setImportance(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  if (!selectedEvent) return null;

  const { region, lat, lon, events, staticFeatures } = selectedEvent;
  const listed = events.slice(0, MAX_LISTED);
  const remaining = events.length - listed.length;
  const terrainRows = TERRAIN_FIELDS
    .map(([key, label, unit]) => [key, label, unit, staticFeatures?.[key]])
    .filter(([, , , v]) => v !== null && v !== undefined);
  const anyTabpfn = events.find((ev) => ev.tabpfn_risk_score != null);
  const river = events.find((ev) => ev.chronos_station != null);

  const allScored = events
    .filter((ev) => ev.tabpfn_risk_score != null)
    .map((ev) => ({ ev, d: parseEventDate(ev.date) }))
    .filter((x) => x.d)
    .sort((a, b) => a.d - b.d)
    .map((x) => ({ score: x.ev.tabpfn_risk_score, tier: x.ev.tabpfn_tier, date: x.ev.date, year: x.d.getFullYear() }));
  // All-time highest stays all-time (most severe real event on record); the
  // trend sparkline below is scoped to only the most recent year present in
  // this location's real data, per request -- older years dropped from the trend.
  const topScored = allScored.length
    ? allScored.reduce((a, b) => (b.score > a.score ? b : a))
    : null;
  const latestYear = allScored.length ? Math.max(...allScored.map((s) => s.year)) : null;
  const scoredChrono = allScored.filter((s) => s.year === latestYear);

  return (
    <div className="panel" style={{ borderColor: '#38bdf8' }}>
      <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>{region}</span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: '#8b949e',
            cursor: 'pointer', fontSize: 14, padding: 0,
          }}
          title="Back to live view"
        >
          ✕
        </button>
      </div>

      <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>
        {lat?.toFixed(4)}° N, {lon?.toFixed(4)}° E
      </div>

      <div style={{
        display: 'inline-block', fontSize: 10, fontWeight: 700,
        color: '#38bdf8', border: '1px solid #38bdf8', borderRadius: 4,
        padding: '2px 6px', marginBottom: 8,
      }}>
        SOURCED HISTORICAL DATA — NOT A LIVE MODEL OUTPUT
      </div>

      <div style={{ fontSize: 12, color: '#e6edf3', marginBottom: 8 }}>
        <strong>{events.length}</strong> real recorded event{events.length === 1 ? '' : 's'}
        {' '}(India Flood Inventory v3, IMD-sourced)
      </div>

      {topScored && (
        <div style={{
          marginBottom: 10, borderRadius: 6, padding: '10px 12px',
          background: `${TIER_COLORS[topScored.tier] || '#38bdf8'}1a`,
          border: `1px solid ${TIER_COLORS[topScored.tier] || '#38bdf8'}`,
        }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', letterSpacing: 0.5, marginBottom: 2 }}>
            HIGHEST RECORDED TabPFN SCORE AT THIS LOCATION
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 30, fontWeight: 800, color: TIER_COLORS[topScored.tier] || '#38bdf8' }}>
              {Math.round(topScored.score)}
            </span>
            <span style={{ fontSize: 13, color: '#8b949e' }}>/100</span>
            <span style={{
              marginLeft: 4, fontSize: 11, fontWeight: 700, borderRadius: 4, padding: '2px 8px',
              color: TIER_COLORS[topScored.tier] || '#8b949e',
              border: `1px solid ${TIER_COLORS[topScored.tier] || '#8b949e'}`,
            }}>
              {topScored.tier}
            </span>
            <span style={{ fontSize: 10, color: '#6e7681', marginLeft: 'auto' }}>
              {topScored.date}
            </span>
          </div>
          {scoredChrono.length > 1 && (
            <div>
              <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>
                Score trend across {scoredChrono.length} real dated events in {latestYear} (most recent year on record)
              </div>
              <TrendSparkline points={scoredChrono} />
            </div>
          )}
        </div>
      )}

      {terrainRows.length > 0 && (
        <div style={{ marginBottom: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4, letterSpacing: 0.5 }}>
            TERRAIN PROFILE (real, SRTM 30m + pysheds)
          </div>
          {terrainRows.map(([key, label, unit, v]) => (
            <div key={key} style={{
              display: 'flex', justifyContent: 'space-between',
              fontSize: 11, padding: '2px 0', color: '#c9d1d9',
            }}>
              <span>{label}</span>
              <span style={{ fontWeight: 600 }}>
                {typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v}{unit ? ` ${unit}` : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {anyTabpfn && importance?.features?.length > 0 && (
        <div style={{ marginBottom: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4, letterSpacing: 0.5 }}>
            TOP CONTRIBUTING FACTORS (TabPFN, global ranking)
          </div>
          {importance.features.slice(0, 6).map((f) => {
            const max = importance.features[0].importance_mean || 1;
            const pct = Math.max(4, Math.round((f.importance_mean / max) * 100));
            return (
              <div key={f.name} style={{ marginBottom: 5 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#c9d1d9' }}>
                  <span>{FEATURE_LABELS[f.name] || f.name}</span>
                  <span style={{ color: '#8b949e' }}>{f.importance_mean.toFixed(3)}</span>
                </div>
                <div style={{ height: 4, background: '#21262d', borderRadius: 2 }}>
                  <div style={{ width: `${pct}%`, height: 4, background: '#38bdf8', borderRadius: 2 }} />
                </div>
              </div>
            );
          })}
          <div style={{ fontSize: 9, color: '#6e7681', marginTop: 4, lineHeight: 1.4 }}>
            {importance.caveat}
          </div>
        </div>
      )}

      {river && (
        <div style={{ marginBottom: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4, letterSpacing: 0.5 }}>
            RIVER LEVEL FORECAST — {river.chronos_station} (Chronos-Bolt, pretrained)
          </div>
          <div style={{ fontSize: 11, color: '#c9d1d9', marginBottom: 6 }}>
            Lead time: <strong>{river.chronos_prediction_length_steps || river.chronos_forecast_median_m.length}h</strong> ahead (hourly steps, zero-shot)
          </div>
          <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>
            1-day risk trend (river level, median ± real forecast band)
          </div>
          <RiverTrendChart
            median={river.chronos_forecast_median_m}
            low={river.chronos_forecast_low_m}
            high={river.chronos_forecast_high_m}
          />
          <div style={{
            fontSize: 10, color: '#d29922',
            border: '1px solid #92640a', background: 'rgba(146,100,10,0.12)',
            borderRadius: 4, padding: '5px 7px', lineHeight: 1.4,
          }}>
            {river.chronos_caveat}
          </div>
        </div>
      )}

      <div style={{ maxHeight: 220, overflowY: 'auto' }}>
        {listed.map((ev) => (
          <div
            key={ev.event_id}
            style={{
              borderLeft: `3px solid ${TYPE_COLORS[ev.type] || TYPE_COLORS.unknown}`,
              paddingLeft: 8, marginBottom: 8, fontSize: 11,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ color: '#e6edf3', fontWeight: 600 }}>{ev.date || 'date unknown'}</div>
              {ev.tabpfn_risk_score != null && (
                <span style={{
                  fontSize: 10, fontWeight: 700, borderRadius: 3, padding: '1px 5px',
                  color: TIER_COLORS[ev.tabpfn_tier] || '#8b949e',
                  border: `1px solid ${TIER_COLORS[ev.tabpfn_tier] || '#8b949e'}`,
                }}>
                  TabPFN {Math.round(ev.tabpfn_risk_score)}/100 · {ev.tabpfn_tier}
                </span>
              )}
            </div>
            <div style={{ color: '#8b949e' }}>
              {TYPE_LABELS[ev.type] || ev.type || 'unknown'}
              {ev.severity ? ` · ${ev.severity}` : ''}
            </div>
            <div style={{ color: '#6e7681', fontSize: 10 }}>{ev.source}</div>
          </div>
        ))}
        {remaining > 0 && (
          <div style={{ fontSize: 10, color: '#8b949e', fontStyle: 'italic' }}>
            + {remaining} more real event{remaining === 1 ? '' : 's'} not shown
          </div>
        )}
      </div>
    </div>
  );
}
