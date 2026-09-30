/**
 * AlertConsole.jsx — v2 Sec. 16.3 live-operations console strip.
 *
 *  - Region strip: one chip per region, coloured by its worst CURRENT tier (real stored scores), with a word.
 *  - Alert cards for every alert held at the two-person gate: what is happening, what to do, confidence,
 *    AUTH x/2, and approve / reject for two different people in two different roles.
 *  - "Exercise" raises a clearly labelled drill alert for the selected region through the real gate.
 *    While an exercise is open a permanent banner says nothing is being sent.
 * Operator ID and role are self-declared: there is no login yet.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { getPendingGates, approveGate, rejectGate, getRegionStatus, startExercise } from '../api/client';

const TIER_COLOR = { Green: '#22c55e', Yellow: '#eab308', Orange: '#f97316', Red: '#ef4444' };
const POLL_MS = 5_000;
const REGION_POLL_MS = 60_000;
const ROLE_LABEL = { duty_officer: 'duty officer', district_authority: 'district authority' };

function RegionChip({ r, active, onClick }) {
  const c = TIER_COLOR[r.worst_tier];
  return (
    <button onClick={onClick} title={`${r.scored_hexes} scored hexes`}
      style={{
        display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px', borderRadius: 999,
        fontSize: 10, cursor: 'pointer', whiteSpace: 'nowrap',
        border: `1px solid ${active ? 'var(--text-primary, #e6edf3)' : 'var(--edge, #30363d)'}`,
        background: active ? 'rgba(255,255,255,0.06)' : 'transparent', color: 'inherit',
      }}>
      <span style={{ width: 8, height: 8, borderRadius: 4, background: c || '#484f58' }} />
      <span>{r.region_code}</span>
      <span style={{ opacity: 0.75 }}>{r.worst_tier || 'no scores'}</span>
    </button>
  );
}

function AlertCard({ g, onDone }) {
  const [opId, setOpId] = useState('');
  const [role, setRole] = useState(g.roles_needed?.[0] || 'duty_officer');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg]   = useState(null);
  const ctx = g.context || {};
  const tier = ctx.scenario_tier || (g.risk_score >= 75 ? 'Red' : 'Orange');

  const act = async (kind) => {
    if (!opId.trim()) { setMsg({ ok: false, text: 'Enter your operator ID first.' }); return; }
    setBusy(true);
    try {
      if (kind === 'reject') {
        await rejectGate(g.hex_id, opId.trim(), role, 'rejected from console');
        setMsg({ ok: true, text: 'Rejected. Nothing was sent.' });
      } else {
        const r = await approveGate(g.hex_id, opId.trim(), role);
        if (r.action !== 'held') onDone?.(r.action === 'exercise_ready'
          ? `Exercise alert authorised (${r.alert_id}). CAP built with status=Exercise; nothing was sent.`
          : `Alert ${r.alert_id} authorised and released.`);
        setMsg({ ok: true, text: r.action === 'exercise_ready' ? 'Authorised. Exercise CAP built (status=Exercise); nothing was sent.'
                                : r.action === 'fired' ? 'Authorised. Alert released to the configured channels.'
                                : (r.reason || 'Approval recorded.') });
      }
      setOpId('');
      onDone?.(kind === 'reject' ? 'Alert rejected. Nothing was sent.' : null);
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || 'Request failed.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ border: `1px solid ${TIER_COLOR[tier]}66`, background: `${TIER_COLOR[tier]}14`,
                  borderRadius: 8, padding: '8px 10px', minWidth: 280, maxWidth: 420, fontSize: 11, lineHeight: 1.45 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
        {g.exercise && <span style={{ fontSize: 9, fontWeight: 800, padding: '1px 5px', borderRadius: 3,
                                      background: '#a855f7', color: '#fff' }}>EXERCISE</span>}
        <span style={{ fontWeight: 800, color: TIER_COLOR[tier] }}>{tier.toUpperCase()}</span>
        <span>{ctx.hazard || 'hazard'} · {ctx.village || ctx.region_label || ctx.region_code || g.hex_id}</span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
          AUTH {g.approvals_count ?? 0}/{g.approvals_required ?? 2}
        </span>
      </div>
      {ctx.what_is_happening && <div><strong>What is happening:</strong> {ctx.what_is_happening}</div>}
      {ctx.what_to_do && <div><strong>What to do:</strong> {ctx.what_to_do}</div>}
      <div style={{ color: 'var(--text-muted)' }}>
        Confidence {g.confidence != null ? Math.round(g.confidence) : '—'}/100 · lead time{' '}
        {g.lead_time_min != null ? `${Math.round(g.lead_time_min / 60)} h` : 'not projected'} · shelter: see village table
      </div>
      <div style={{ color: 'var(--text-muted)' }}>
        {(g.approvals || []).map((a) => `✓ ${a.operator_id} (${ROLE_LABEL[a.role] || a.role})`).join(' · ') || 'no approvals yet'}
        {g.roles_needed?.length ? ` · waiting for ${g.roles_needed.map((r) => ROLE_LABEL[r] || r).join(', ')}` : ''}
      </div>
      <div style={{ display: 'flex', gap: 5, marginTop: 6, flexWrap: 'wrap' }}>
        <input className="cir-input" placeholder="Operator ID" value={opId} onChange={(e) => setOpId(e.target.value)}
               style={{ flex: 1, minWidth: 90, padding: '4px 6px', fontSize: 11 }} />
        <select className="cir-input" value={role} onChange={(e) => setRole(e.target.value)}
                style={{ padding: '4px 6px', fontSize: 11 }}>
          <option value="duty_officer">Duty officer</option>
          <option value="district_authority">District authority</option>
        </select>
        <button className="cir-btn" disabled={busy} onClick={() => act('approve')}
                style={{ padding: '4px 10px', fontSize: 11, background: 'var(--danger)', color: 'var(--cloud)' }}>Approve</button>
        <button className="cir-btn" disabled={busy} onClick={() => act('reject')}
                style={{ padding: '4px 10px', fontSize: 11 }}>Reject</button>
      </div>
      {msg && <div style={{ marginTop: 4, color: msg.ok ? '#4ade80' : '#f87171' }}>{msg.text}</div>}
    </div>
  );
}

export default function AlertConsole({ selectedRegionCode, onRegionChange, onGatesChange }) {
  const [regions, setRegions] = useState([]);
  const [gates, setGates]     = useState([]);
  const [exMsg, setExMsg]     = useState(null);
  const [notice, setNotice]   = useState(null);
  const [lastExercise, setLastExercise] = useState(false);

  const loadGates = useCallback(() => {
    getPendingGates().then((d) => {
      const list = d.pending_gates || [];
      setGates(list);
      onGatesChange?.(list);
    }).catch(() => {});
  }, [onGatesChange]);

  const loadRegions = useCallback(() => {
    getRegionStatus().then((d) => setRegions(d.regions || [])).catch(() => {});
  }, []);

  useEffect(() => {
    loadGates(); loadRegions();
    const a = setInterval(loadGates, POLL_MS);
    const b = setInterval(loadRegions, REGION_POLL_MS);
    return () => { clearInterval(a); clearInterval(b); };
  }, [loadGates, loadRegions]);

  const exercise = async () => {
    setExMsg(null);
    try {
      await startExercise(selectedRegionCode, 'Red');
      setLastExercise(true);
      loadGates();
    } catch (e) {
      setExMsg(e?.response?.data?.detail || 'Could not start an exercise.');
    }
  };

  const exerciseOpen = lastExercise || gates.some((g) => g.exercise);

  return (
    <div style={{ borderBottom: '1px solid var(--edge, #30363d)' }}>
      {exerciseOpen && (
        <div style={{ background: '#6b21a8', color: '#fff', fontSize: 11, fontWeight: 700, padding: '4px 12px',
                      display: 'flex', alignItems: 'center' }}>
          <span>Simulated feed. Exercise alert, nothing is being sent.</span>
          {!gates.some((g) => g.exercise) && (
            <button onClick={() => setLastExercise(false)} className="cir-btn cir-btn--ghost"
                    style={{ marginLeft: 'auto', padding: '0 8px', fontSize: 10, color: '#fff' }}>End exercise</button>
          )}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '6px 10px', overflowX: 'auto' }}>
        {regions.map((r) => (
          <RegionChip key={r.region_code} r={r} active={r.region_code === selectedRegionCode}
                      onClick={() => onRegionChange?.(r.region_code)} />
        ))}
        <button className="cir-btn cir-btn--ghost" onClick={exercise}
                title="Raise a labelled EXERCISE alert for the selected region (goes through the two-person gate; nothing is sent)"
                style={{ marginLeft: 'auto', padding: '3px 10px', fontSize: 10, whiteSpace: 'nowrap' }}>
          + Exercise alert
        </button>
      </div>
      {notice && <div style={{ fontSize: 11, color: '#4ade80', padding: '0 12px 6px' }}>{notice}</div>}
      {exMsg && <div style={{ fontSize: 11, color: '#f87171', padding: '0 12px 6px' }}>{exMsg}</div>}
      {gates.length > 0 && (
        <div style={{ display: 'flex', gap: 8, padding: '0 10px 8px', overflowX: 'auto' }}>
          {gates.map((g) => <AlertCard key={g.hex_id} g={g} onDone={(t) => { if (t) setNotice(t); loadGates(); }} />)}
        </div>
      )}
    </div>
  );
}
