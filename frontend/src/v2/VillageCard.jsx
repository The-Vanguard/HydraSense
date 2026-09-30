/**
 * VillageCard.jsx — right column: the selected village (or hex), why it is at this level, its trend,
 * where its alert is in the two-person workflow, and the nearest shelter.
 * Flood per village is not built: it is shown as such, never estimated.
 */
import React, { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { getEvacuation } from '../api/client';
import { TIER_COLOR, TIER_WORD, REGION_NAMES, FEATURE_LABEL, tierFromScore } from './tiers';

const r0 = (x) => (x == null ? '—' : Math.round(x));

export function Stepper({ gate }) {
  const n = gate?.approvals_count ?? 0;
  const dispatched = gate?.status === 'DISPATCHED' || gate?.status === 'APPROVED';
  const steps = [
    ['Draft', gate ? 'done' : 'current'],
    ['Officer 1', n >= 1 ? 'done' : gate ? 'current' : ''],
    ['Officer 2', n >= 2 ? 'done' : n === 1 ? 'current' : ''],
    [gate?.exercise ? 'Exercise ready' : 'Dispatch', dispatched ? 'done' : n >= 2 ? 'current' : ''],
  ];
  return (
    <div className="hs2-steps">
      {steps.map(([label, st], i) => (
        <React.Fragment key={label}>
          {i > 0 && <span className="hs2-step-sep">›</span>}
          <span className={`hs2-step ${st}`}>{st === 'done' ? '✓ ' : ''}{label}</span>
        </React.Fragment>
      ))}
    </div>
  );
}

function Why({ risk, factors }) {
  const contribs = (risk?.top_contributing_features || []).filter((c) => c && c.contribution != null);
  const total = risk?.risk_score || 0;
  const inputs = risk?.inputs || {};
  return (
    <div className="hs2-card">
      <div className="hs2-card-title">ⓘ Why this level?
        <span className="right faint" style={{ fontSize: 10 }}>share of the score</span></div>
      {contribs.length === 0 && <div className="hs2-empty">No contribution breakdown stored for this score.</div>}
      <div className="hs2-why">
        {contribs.map((c) => {
          const pct = total > 0 ? Math.max(0, Math.min(100, (c.contribution / total) * 100)) : 0;
          return (
            <React.Fragment key={c.feature}>
              <span>{FEATURE_LABEL[c.feature] || c.feature}</span>
              <div className="hs2-bar"><div style={{ width: `${pct}%`, background: pct > 60 ? '#dc2626' : pct > 30 ? '#ea580c' : '#3b82f6' }} /></div>
              <span className="num" style={{ textAlign: 'right' }}>{Math.round(pct)}%</span>
            </React.Fragment>
          );
        })}
      </div>
      <div className="muted" style={{ fontSize: 11, marginTop: 8, lineHeight: 1.5 }}>
        Inputs used: rain 6 h <span className="num">{inputs.rainfall_6h ?? '—'}</span> mm · 24 h{' '}
        <span className="num">{inputs.rainfall_24h ?? '—'}</span> mm · soil saturation{' '}
        <span className="num">{inputs.soil_saturation_ratio != null ? `${Math.round(inputs.soil_saturation_ratio * 100)}%` : '—'}</span>
        {factors?.primary_reason && <> · confidence limited by <strong>{factors.primary_reason}</strong></>}
      </div>
    </div>
  );
}

function Trend({ history }) {
  const data = (history || []).map((h) => ({
    t: new Date(h.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }),
    Overall: h.risk_score != null ? +h.risk_score.toFixed(1) : null,
    Landslide: h.index_landslide != null ? +h.index_landslide.toFixed(1) : null,
    Flood: h.index_flood != null ? +h.index_flood.toFixed(1) : null,
  }));
  const hasSplit = data.some((x) => x.Landslide != null || x.Flood != null);
  return (
    <div className="hs2-card">
      <div className="hs2-card-title">📈 Risk trend <span className="right faint" style={{ fontSize: 10 }}>last {data.length} scores</span></div>
      {data.length < 2 ? <div className="hs2-empty">Not enough stored scores for a trend yet.</div> : (
        <div style={{ height: 150 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 5, right: 8, left: -24, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--c-border)" />
              <XAxis dataKey="t" tick={{ fontSize: 9 }} interval="preserveStartEnd" />
              <YAxis domain={[0, 100]} tick={{ fontSize: 9 }} />
              <Tooltip contentStyle={{ fontSize: 11 }} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line type="monotone" dataKey="Overall" stroke="#64748b" dot={false} strokeWidth={2} connectNulls />
              {hasSplit && <Line type="monotone" dataKey="Landslide" stroke="#ea580c" dot={false} connectNulls />}
              {hasSplit && <Line type="monotone" dataKey="Flood" stroke="#2563eb" dot={false} connectNulls />}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {data.length >= 2 && !hasSplit && <div className="faint" style={{ fontSize: 10 }}>Flood / landslide lines appear for scores stored from now on.</div>}
    </div>
  );
}

export default function VillageCard({ d, onOpenAlerts }) {
  const { village, risk, factors, history, selectedHexId, selectedVillage } = d;
  const [evac, setEvac] = useState(null);
  useEffect(() => {
    setEvac(null);
    if (!selectedVillage) return;
    getEvacuation(selectedVillage.village_id, selectedVillage.region_code).then(setEvac)
      .catch(() => setEvac({ note: 'shelter advisory unavailable' }));
  }, [selectedVillage]);

  if (!selectedHexId && !selectedVillage) {
    return <div className="hs2-card"><div className="hs2-empty">
      {d.summaryError ? 'No villages available.' : 'Select a region, a village or a hex on the map.'}</div></div>;
  }

  const tier = village?.alert_tier || risk?.tier;
  const lsValue = village?.alert_value ?? risk?.risk_score;
  const last = history[history.length - 1];
  const floodIdx = last?.index_flood;
  const lead = risk?.lead_time_min;
  const gate = d.gates.find((g) => g.hex_id === selectedHexId || g.context?.real_hex_id === selectedHexId);
  const regionCode = village?.region_code || selectedVillage?.region_code || d.region;

  return (
    <div>
      <div className="hs2-card">
        <div className="hs2-vhead">
          <span style={{ fontSize: 22, color: TIER_COLOR[tier] || '#94a3b8' }}>▲</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="name">{village?.name || (selectedVillage ? 'Loading…' : `Hex ${selectedHexId}`)}</div>
            <div className="muted" style={{ fontSize: 12 }}>{REGION_NAMES[regionCode] || regionCode}
              {village?.boundary_quality ? ` · boundary: ${village.boundary_quality}` : ''}</div>
          </div>
          {tier && <span className="hs2-tierbadge" style={{ background: TIER_COLOR[tier] }}>{TIER_WORD[tier].toUpperCase()} RISK</span>}
        </div>
        {d.villageErr && <div className="hs2-banner" style={{ marginTop: 8 }}>{d.villageErr}</div>}
        <div className="hs2-metrics">
          <div className="hs2-metric">
            <div className="k">Flood risk (village)</div>
            <div className="v" style={{ fontSize: 13, color: 'var(--c-muted)' }}>not built yet</div>
            <div className="faint" style={{ fontSize: 10 }}>{floodIdx != null ? `hex flood index ${r0(floodIdx)}/100` : 'per-catchment flood head pending'}</div>
          </div>
          <div className="hs2-metric">
            <div className="k">Landslide risk</div>
            <div className="v num" style={{ color: TIER_COLOR[tierFromScore(lsValue)] }}>{r0(lsValue)}<small> / 100</small></div>
            <div className="faint" style={{ fontSize: 10 }}>{village ? `driven by ${village.alert_driver === 'upslope_source' ? 'upslope source' : 'inside village'}` : 'hex score'}</div>
          </div>
          <div className="hs2-metric">
            <div className="k">Confidence</div>
            <div className="v num">{factors ? r0(factors.confidence_score) : risk?.confidence_score != null ? r0(risk.confidence_score) : '—'}<small> / 100</small></div>
            <div className="faint" style={{ fontSize: 10 }}>{factors ? `${factors.confidence_short_word} · ${factors.primary_reason}` : 'indicator, not a probability'}</div>
          </div>
          <div className="hs2-metric">
            <div className="k">Lead time</div>
            <div className="v num" style={{ fontSize: lead == null ? 13 : 20 }}>{lead == null ? 'not projected' : `${Math.round(lead / 60)} h`}</div>
            <div className="faint" style={{ fontSize: 10 }}>{(risk?.lead_time_basis || '').replace(/_/g, ' ') || '—'}</div>
          </div>
        </div>
      </div>

      <Why risk={risk} factors={factors} />
      <Trend history={history} />

      <div className="hs2-card">
        <div className="hs2-card-title">📄 Incident action plan
          <span className="right">{gate ? <span className={`hs2-tag ${gate.exercise ? 'sim' : 'warn'}`}>{gate.exercise ? 'Exercise' : 'Pending approval'}</span>
            : <span className="hs2-tag">No alert drafted</span>}</span></div>
        <Stepper gate={gate} />
        <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
          {gate ? <>Held for two-person authorisation (duty officer + district authority). <button className="hs2-btn small" onClick={onOpenAlerts}>Open alerts</button></>
            : tier === 'Red' || tier === 'Orange'
              ? 'At alert level; a draft is raised after 2 consecutive cycles (v2 persistence rule).'
              : 'Below alert level: nothing to authorise.'}
        </div>
        <div style={{ borderTop: '1px solid var(--c-border)', marginTop: 10, paddingTop: 8, fontSize: 12 }}>
          <strong>🏠 Nearest shelter</strong>
          <div className="muted" style={{ fontSize: 11 }}>
            {!selectedVillage ? 'Select a village to see shelter advice.'
              : !evac ? 'Loading…'
              : evac.shelters?.length
                ? evac.shelters.map((s) => `${s.name} · ${Number(s.distance_km).toFixed(1)} km straight-line${s.capacity ? ` · capacity ${s.capacity}` : ''}`).join(' | ')
                : (evac.note || 'none listed')}
          </div>
          <div className="faint" style={{ fontSize: 10 }}>Advisory only; routed, blockage-aware paths are not built.</div>
        </div>
        <div style={{ borderTop: '1px solid var(--c-border)', marginTop: 8, paddingTop: 8, fontSize: 12, display: 'flex' }}>
          <strong>📡 Sensor health (village)</strong>
          <span className="hs2-tag" style={{ marginLeft: 'auto' }}>no sensors deployed</span>
        </div>
      </div>
    </div>
  );
}
