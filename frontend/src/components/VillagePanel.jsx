/**
 * VillagePanel.jsx — village table + village detail (v2 Sec. 5.3, 11, 13.3).
 *
 * Ranked by landslide alert value only: exposure and vulnerability are not built, so the table says so.
 * Flood per village is not built yet and is shown as such (never blank, never estimated).
 * Shelter advice is straight-line distance from the backend, not a routed path.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { getVillagePriority, getEvacuation } from '../api/client';

const TIER_COLOR = { Green: '#22c55e', Yellow: '#eab308', Orange: '#f97316', Red: '#ef4444' };
const DRIVER = { footprint: 'inside village', upslope_source: 'upslope source' };
const POLL_MS = 60_000;

function Chip({ tier }) {
  if (!tier) return <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>not scored</span>;
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
                   color: '#0b0f14', background: TIER_COLOR[tier] }}>{tier}</span>
  );
}

function Detail({ v, region }) {
  const [evac, setEvac] = useState(null);
  useEffect(() => {
    setEvac(null);
    getEvacuation(v.village_id, region).then(setEvac)
      .catch(() => setEvac({ note: 'shelter advisory unavailable' }));
  }, [v.village_id, region]);
  const fmt = (x) => (x == null ? '—' : Math.round(x));
  return (
    <div style={{ padding: '8px 10px', background: 'var(--bg-card)', borderRadius: 6, fontSize: 11, lineHeight: 1.5 }}>
      <div><strong>Landslide:</strong> {fmt(v.alert_value)} <Chip tier={v.alert_tier} />{' '}
        driven by {DRIVER[v.alert_driver] || v.alert_driver || '—'}</div>
      <div style={{ color: 'var(--text-muted)' }}>
        footprint P90 {fmt(v.footprint_p90)} · upslope reach max {fmt(v.source_reach_max)} ·{' '}
        {v.footprint_hexes_scored}/{v.footprint_hex_count} footprint hexes scored
      </div>
      <div><strong>Flood:</strong> <span style={{ color: 'var(--text-muted)' }}>not built yet (no per-village flood value)</span></div>
      <div style={{ color: 'var(--text-muted)' }}>
        boundary: {v.boundary_quality}{v.footprint_approx ? ' (approximate footprint)' : ''} ·{' '}
        inputs: {(v.data_sources || []).join(', ') || '—'}
      </div>
      <div style={{ marginTop: 4 }}><strong>Nearest shelter:</strong>{' '}
        {!evac ? 'loading…'
          : evac.shelters?.length
            ? evac.shelters.map((s) => `${s.name} (${Number(s.distance_km).toFixed(1)} km)`).join(' · ')
            : (evac.note || 'none listed')}
      </div>
      {evac?.basis && <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>Advisory only: {evac.basis}</div>}
    </div>
  );
}

export default function VillagePanel({ region }) {
  const [data, setData]    = useState(null);
  const [err, setErr]      = useState(null);
  const [open, setOpen]    = useState(null);
  const [sortKey, setSort] = useState('priority');

  const load = useCallback(() => {
    if (!region) return;
    getVillagePriority(region).then((d) => { setData(d); setErr(null); })
      .catch((e) => setErr(e?.response?.data?.detail || 'village table unavailable'));
  }, [region]);

  useEffect(() => {
    setData(null); setOpen(null); load();
    const iv = setInterval(load, POLL_MS);
    return () => clearInterval(iv);
  }, [load]);

  if (!region) return null;
  let rows = data?.villages || [];
  if (sortKey === 'name') rows = [...rows].sort((a, b) => (a.name || '').localeCompare(b.name || ''));

  return (
    <div className="panel">
      <div className="panel-title" style={{ display: 'flex', alignItems: 'center' }}>
        <span>Villages</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 400 }}>
          sort:{' '}
          {['priority', 'name'].map((k) => (
            <button key={k} className="cir-btn cir-btn--ghost" onClick={() => setSort(k)}
                    style={{ padding: '1px 6px', fontSize: 10, opacity: sortKey === k ? 1 : 0.6 }}>{k}</button>
          ))}
        </span>
      </div>
      {err && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{err}</div>}
      {!data && !err && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Loading villages…</div>}
      {data && (
        <>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 6 }}>
            {data.count} villages · ranked by landslide risk only (exposure and vulnerability not built yet)
          </div>
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
                  <th>#</th><th>Village</th><th>Tier</th><th style={{ textAlign: 'right' }}>Value</th><th>Flood</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((v) => (
                  <React.Fragment key={v.village_id}>
                    <tr onClick={() => setOpen(open === v.village_id ? null : v.village_id)}
                        style={{ cursor: 'pointer', borderTop: '1px solid var(--edge)' }}>
                      <td>{v.priority_rank ?? '—'}</td>
                      <td>{v.name || v.village_id}</td>
                      <td><Chip tier={v.alert_tier} /></td>
                      <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                        {v.alert_value == null ? '—' : Math.round(v.alert_value)}
                      </td>
                      <td style={{ color: 'var(--text-muted)' }}>n/a</td>
                    </tr>
                    {open === v.village_id && (
                      <tr><td colSpan={5}><Detail v={v} region={region} /></td></tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
