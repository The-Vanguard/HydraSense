/**
 * ManualScenarioPanel.jsx
 * Manual "what-if" scenario form. User enters hypothetical feature values;
 * the backend runs them through the REAL trained Wayanad FusionModel
 * (POST /simulate/risk) -- the score is a genuine model computation, not a
 * fabricated number, but the INPUT is explicitly a hypothetical, never
 * presented as a live sensor reading.
 *
 * On Orange/Red the backend also fires a real ntfy.sh push (server-side
 * dedup) -- alert_fired/alert_detail below reflect what the server actually
 * did, not an assumption made here.
 */
import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { simulateRisk, getSimulationPoints } from '../api/client';

// SRS §10.4 frozen tier boundaries -- same thresholds TrendLine.jsx uses for live hexes.
const TIER_THRESHOLDS = [
  { value: 30, tier: 'Yellow', color: '#eab308' },
  { value: 55, tier: 'Orange', color: '#f97316' },
  { value: 75, tier: 'Red',    color: '#ef4444' },
];

function formatLeadTime(minutes) {
  if (minutes === null || minutes === undefined) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}min`;
}

function formatHour(ts) {
  try {
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
  } catch { return ''; }
}

const STATIC_FIELD_KEYS = [
  'slope_deg', 'aspect', 'TWI', 'TRI', 'elevation', 'distance_to_stream_m',
  'drainage_density', 'land_use_class', 'ndvi_mean', 'historical_event_count_500m',
  'gsi_susceptibility_class',
];

const TIER_COLORS = { Green: '#22c55e', Yellow: '#eab308', Orange: '#f97316', Red: '#ef4444' };

// Grouped to match the frozen STATIC_FEATURE_COLS / DYNAMIC_FEATURE_COLS
// schema (ml/models/train_fusion_model.py) -- field names are frozen, never
// renamed here.
const NUMERIC_FIELDS = [
  ['Terrain', [
    ['slope_deg', 'Slope (deg)'], ['aspect', 'Aspect (deg)'], ['TWI', 'Topographic wetness index'],
    ['TRI', 'Terrain roughness index'], ['elevation', 'Elevation (m)'],
    ['distance_to_stream_m', 'Distance to stream (m)'], ['drainage_density', 'Drainage density'],
    ['ndvi_mean', 'NDVI mean'], ['historical_event_count_500m', 'Historical events within 500m'],
  ]],
  ['Rainfall', [
    ['rainfall_1h', 'Rainfall 1h (mm)'], ['rainfall_3h', 'Rainfall 3h (mm)'],
    ['rainfall_6h', 'Rainfall 6h (mm)'], ['rainfall_24h', 'Rainfall 24h (mm)'],
    ['rainfall_72h_antecedent', 'Rainfall 72h antecedent (mm)'],
    ['rain_intensity_mm_hr', 'Rain intensity (mm/hr)'],
    ['antecedent_precipitation_index', 'Antecedent precipitation index'],
  ]],
  ['Soil & Stability', [
    ['soil_saturation_ratio', 'Soil saturation ratio (0-1)'],
    ['factor_of_safety', 'Factor of safety'],
    ['factor_of_safety_min', 'Factor of safety (min)'],
    ['factor_of_safety_max', 'Factor of safety (max)'],
  ]],
];

const LAND_USE_OPTIONS = ['Water', 'Urban', 'Cropland', 'Grassland', 'Shrubland', 'Forest', 'Bare'];
const GSI_OPTIONS = ['Low', 'Moderate', 'High', 'Very High'];
const BOOL_FIELDS = [
  ['simulated_ffgs_signal', 'FFGS signal active'],
  ['simulated_gsi_signal', 'GSI signal active'],
  ['iot_anomaly_flag', 'IoT anomaly flagged'],
];

export default function ManualScenarioPanel({ onClose, externalPointRequest }) {
  const [values, setValues] = useState({});
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [points, setPoints] = useState([]);
  const [selectedPointId, setSelectedPointId] = useState('');
  const [pointNote, setPointNote] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getSimulationPoints().then((data) => { if (!cancelled) setPoints(data); }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const setField = (key, val) => setValues((v) => ({ ...v, [key]: val }));

  const handlePointSelect = (hexId) => {
    setSelectedPointId(hexId);
    if (!hexId) { setPointNote(null); return; }
    const pt = points.find((p) => p.hex_id === hexId);
    if (!pt) return;
    if (pt.has_real_static_features) {
      const prefill = {};
      for (const k of STATIC_FIELD_KEYS) {
        if (pt.static_features[k] !== undefined && pt.static_features[k] !== null) prefill[k] = pt.static_features[k];
      }
      setValues((v) => ({ ...v, ...prefill }));
      const unmapped = pt.unmapped_fields?.length
        ? ` ${pt.unmapped_fields.length} field(s) left blank (no real data for this location): ${pt.unmapped_fields.join(', ')}.`
        : '';
      setPointNote((pt.note || `Pre-filled terrain fields from real data at ${pt.label}.`) + unmapped);
    } else {
      setPointNote(
        `${pt.label} (${pt.lat.toFixed(4)}°, ${pt.lon.toFixed(4)}°) has no real terrain data recorded yet ` +
        `(known gap, tracked separately) — enter values manually below.`
      );
    }
  };

  // Clicking a real pin/hex on the map while this panel is open loads that
  // point's data the same way picking it from the dropdown does (App.jsx
  // redirects map clicks here instead of switching views while scenario
  // mode is active).
  useEffect(() => {
    if (externalPointRequest?.hexId) handlePointSelect(externalPointRequest.hexId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalPointRequest, points]);

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = {};
      for (const [k, v] of Object.entries(values)) {
        if (v === '' || v === undefined) continue;
        payload[k] = v;
      }
      if (selectedPointId) payload.hex_id = selectedPointId;
      const data = await simulateRisk(payload);
      setResult(data);
    } catch (e) {
      setError(e?.response?.data?.detail ? JSON.stringify(e.response.data.detail) : 'Simulation request failed');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => { setValues({}); setResult(null); setError(null); setSelectedPointId(''); setPointNote(null); };

  return (
    <div className="panel" style={{ borderColor: '#a78bfa' }}>
      <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Manual Scenario</span>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: 14, padding: 0 }} title="Close">✕</button>
      </div>

      <div style={{ marginBottom: 10 }}>
        <label style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', display: 'block', marginBottom: 4 }}>
          START FROM A REAL POINT (optional)
        </label>
        <select
          value={selectedPointId}
          onChange={(e) => handlePointSelect(e.target.value)}
          style={{ width: '100%', background: '#0d1117', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3', fontSize: 11, padding: '5px 6px' }}
        >
          <option value="">— none —</option>
          {['Wayanad pilot', 'Other real locations (partial terrain only)'].map((group) => {
            const inGroup = points.filter((p) => (p.group || 'Wayanad pilot') === group);
            if (!inGroup.length) return null;
            return (
              <optgroup key={group} label={group}>
                {inGroup.map((p) => (
                  <option key={p.hex_id} value={p.hex_id}>
                    {p.label} {p.has_real_static_features ? '' : '(no terrain data yet)'}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </select>
        {pointNote && (
          <div style={{ fontSize: 10, color: '#8b949e', marginTop: 4, lineHeight: 1.4 }}>{pointNote}</div>
        )}
      </div>

      <div style={{ maxHeight: 320, overflowY: 'auto', marginBottom: 10 }}>
        {NUMERIC_FIELDS.map(([group, fields]) => (
          <div key={group} style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4 }}>{group.toUpperCase()}</div>
            {fields.map(([key, label]) => (
              <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <label style={{ fontSize: 11, color: '#c9d1d9' }}>{label}</label>
                <input
                  type="number" step="any" value={values[key] ?? ''}
                  onChange={(e) => setField(key, e.target.value === '' ? '' : Number(e.target.value))}
                  style={{ width: 90, background: '#0d1117', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3', fontSize: 11, padding: '3px 6px' }}
                />
              </div>
            ))}
          </div>
        ))}

        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4 }}>LAND / SUSCEPTIBILITY</div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <label style={{ fontSize: 11, color: '#c9d1d9' }}>Land use class</label>
            <select value={values.land_use_class ?? ''} onChange={(e) => setField('land_use_class', e.target.value || undefined)}
              style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3', fontSize: 11, padding: '3px 6px' }}>
              <option value="">—</option>
              {LAND_USE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <label style={{ fontSize: 11, color: '#c9d1d9' }}>GSI susceptibility</label>
            <select value={values.gsi_susceptibility_class ?? ''} onChange={(e) => setField('gsi_susceptibility_class', e.target.value || undefined)}
              style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3', fontSize: 11, padding: '3px 6px' }}>
              <option value="">—</option>
              {GSI_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
        </div>

        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4 }}>SIGNALS</div>
          {BOOL_FIELDS.map(([key, label]) => (
            <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <label style={{ fontSize: 11, color: '#c9d1d9' }}>{label}</label>
              <input type="checkbox" checked={!!values[key]} onChange={(e) => setField(key, e.target.checked)} />
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <button onClick={handleSubmit} disabled={loading}
          style={{ flex: 1, background: '#a78bfa', border: 'none', borderRadius: 6, color: '#0d1117', fontWeight: 700, fontSize: 12, padding: '8px 0', cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.6 : 1 }}>
          {loading ? 'Scoring…' : 'Run Scenario'}
        </button>
        <button onClick={handleReset}
          style={{ background: 'none', border: '1px solid #30363d', borderRadius: 6, color: '#8b949e', fontSize: 12, padding: '8px 12px', cursor: 'pointer' }}>
          Reset
        </button>
      </div>

      {error && (
        <div style={{ fontSize: 11, color: '#ef4444', marginBottom: 10 }}>{error}</div>
      )}

      {result && (
        <div style={{ borderTop: '1px solid #30363d', paddingTop: 10 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 28, fontWeight: 800, color: TIER_COLORS[result.tier] || '#8b949e' }}>{result.risk_score}</span>
            <span style={{ fontSize: 12, color: '#8b949e' }}>/100</span>
            <span style={{
              fontSize: 11, fontWeight: 700, borderRadius: 4, padding: '2px 8px',
              color: TIER_COLORS[result.tier] || '#8b949e', border: `1px solid ${TIER_COLORS[result.tier] || '#8b949e'}`,
            }}>{result.tier}</span>
          </div>
          <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>
            Confidence {result.confidence_score}% · {result.n_fields_provided}/{result.n_fields_total} fields provided
          </div>

          {result.sparse_input_warning && (
            <div style={{
              fontSize: 10, color: '#d29922', border: '1px solid #92640a', background: 'rgba(146,100,10,0.12)',
              borderRadius: 4, padding: '6px 8px', marginBottom: 8, lineHeight: 1.4,
            }}>
              {result.sparse_input_warning}
            </div>
          )}

          {/* Lead time -- real SRS §12 forecast walk (backend/lead_time.py's
              method), run against real Open-Meteo rainfall for the selected
              point merged with the hypothetical inputs above. */}
          <div style={{ borderTop: '1px solid #30363d', paddingTop: 10, marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: '#8b949e' }}>Lead time (Red crossing)</span>
              <span style={{
                fontSize: 9, color: '#6e7681', border: '1px solid #30363d', borderRadius: 3, padding: '1px 5px',
              }}>
                {result.forecast_data_source === 'cached_demo' ? 'cached forecast (live call failed)' : 'live Open-Meteo forecast'}
              </span>
            </div>
            {result.lead_time_basis === 'no_red_crossing_in_forecast_window' ? (
              <div style={{ fontSize: 12, color: '#8b949e' }}>no_red_crossing_in_forecast_window</div>
            ) : (
              <>
                <div style={{ fontSize: 22, fontWeight: 800, color: '#e6edf3' }}>
                  {formatLeadTime(result.lead_time_min) ?? '—'}
                </div>
                <div style={{ fontSize: 9, color: '#484f58' }}>{result.lead_time_basis}</div>
              </>
            )}
          </div>

          {/* Factor of safety -- only the value(s) you typed in above, echoed
              back for the gauge (never computed/guessed here). */}
          {result.factor_of_safety != null && (
            <div style={{ marginBottom: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 11 }}>
                <span style={{ color: '#8b949e' }}>Factor of safety (FS)</span>
                <span style={{
                  fontWeight: 700,
                  color: result.factor_of_safety < 1.0 ? '#ef4444' : result.factor_of_safety < 1.3 ? '#f97316' : '#22c55e',
                }}>
                  {result.factor_of_safety.toFixed(2)}
                </span>
              </div>
              {result.factor_of_safety_min != null && result.factor_of_safety_max != null && (
                <div style={{ fontSize: 9, color: '#484f58' }}>
                  Band: {result.factor_of_safety_min.toFixed(2)} – {result.factor_of_safety_max.toFixed(2)}
                  {result.factor_of_safety_min < 1.0 && result.factor_of_safety_max >= 1.0 && (
                    <span style={{ color: '#ef4444' }}> · straddles failure threshold</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 24h forward projection -- real forecast rainfall re-run through
              the real model at each hourly step; NOT a historical trend. */}
          {result.projected_trend?.length > 1 && (
            <div style={{ marginBottom: 10, borderTop: '1px solid #30363d', paddingTop: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 4, letterSpacing: 0.5 }}>
                RISK SCORE — 24H PROJECTION
              </div>
              <ResponsiveContainer width="100%" height={110}>
                <LineChart
                  data={result.projected_trend.map((p) => ({ time: formatHour(p.timestamp), score: p.risk_score, tier: p.tier }))}
                  margin={{ top: 4, right: 4, left: -24, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
                  <XAxis dataKey="time" tick={{ fontSize: 9, fill: '#8b949e' }} interval="preserveStartEnd" />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: '#8b949e' }} width={32} />
                  <Tooltip contentStyle={{ background: '#21262d', border: '1px solid #30363d', fontSize: 11 }} labelStyle={{ color: '#8b949e' }} />
                  {TIER_THRESHOLDS.map((t) => (
                    <ReferenceLine
                      key={t.tier} y={t.value} stroke={t.color} strokeDasharray="4 3" strokeOpacity={0.5}
                      label={{ value: t.tier, position: 'insideTopLeft', fontSize: 8, fill: t.color }}
                    />
                  ))}
                  <Line type="monotone" dataKey="score" stroke="#a78bfa" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: '#a78bfa' }} />
                </LineChart>
              </ResponsiveContainer>
              <div style={{ fontSize: 9, color: '#6e7681', marginTop: 4, lineHeight: 1.4 }}>
                {result.projected_trend_caveat}
              </div>
            </div>
          )}

          <div style={{
            fontSize: 10, color: result.alert_fired ? '#22c55e' : '#8b949e',
            border: '1px solid #30363d', borderRadius: 4, padding: '6px 8px', lineHeight: 1.4,
          }}>
            {result.alert_detail}
          </div>
        </div>
      )}
    </div>
  );
}
