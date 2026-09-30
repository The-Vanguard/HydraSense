/**
 * GatePanel.jsx — Two-Person Red Alert Gate UI (Stage 6 / Final.md §17.4)
 *
 * Polls GET /alert/gate/pending every 5s.
 * Shows a prominent red alert for each pending Red gate.
 * Two different people in two different roles (duty officer + district authority) must approve
 * before the alert is sent.  Either can reject.  IDs/roles are self-declared (no login yet).
 */
import React, { useState, useEffect, useCallback } from 'react';
import { getPendingGates, approveGate, rejectGate } from '../api/client';

const POLL_MS = 5_000;

export default function GatePanel({ hexId }) {
  const [gates,      setGates]      = useState([]);
  const [opId,       setOpId]       = useState('');
  const [approving,  setApproving]  = useState(null);
  const [result,     setResult]     = useState(null);
  const [loading,    setLoading]    = useState(false);

  const fetchGates = useCallback(() => {
    getPendingGates()
      .then((data) => {
        const all = data.pending_gates || [];
        // Only show the gate for the currently selected hex
        const relevant = hexId ? all.filter(g => g.hex_id === hexId) : [];
        setGates(relevant);
      })
      .catch(() => {});
  }, [hexId]);

  useEffect(() => {
    fetchGates();
    const iv = setInterval(fetchGates, POLL_MS);
    return () => clearInterval(iv);
  }, [fetchGates]);

  const [role, setRole] = useState('duty_officer');

  // Reset result message when hex changes
  useEffect(() => { setResult(null); }, [hexId]);

  const act = async (gHexId, kind) => {
    if (!opId.trim()) {
      setResult({ success: false, message: 'Enter your operator ID first.' });
      return;
    }
    setLoading(true);
    setApproving(gHexId);
    try {
      if (kind === 'reject') {
        await rejectGate(gHexId, opId.trim(), role, 'rejected from dashboard');
        setResult({ success: true, message: 'Alert rejected. Nothing was sent.' });
      } else {
        const res = await approveGate(gHexId, opId.trim(), role);
        setResult({ success: true, message: res.action === 'fired'
          ? 'Second approval recorded. Alert released.'
          : (res.reason || 'Approval recorded, waiting for the second person.') });
      }
      fetchGates();
    } catch (e) {
      setResult({ success: false, message: e?.response?.data?.detail || 'Request failed.' });
    } finally {
      setLoading(false);
      setApproving(null);
    }
  };

  if (gates.length === 0) return null;

  return (
    <div className="panel gate-panel">
      <div className="panel-title" style={{ color: 'var(--danger)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16 }}>🔴</span>
        <span>Red Alert Gate Approval</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-muted)', fontWeight: 400, fontFamily: 'var(--font-mono)' }}>
          {gates[0]?.hex_id?.slice(0, 12)}…
        </span>
      </div>

      <p style={{ fontSize: 11, color: 'var(--danger)', marginBottom: 10, lineHeight: 1.5, opacity: 0.85 }}>
        Two different operators (duty officer + district authority) must approve before this alert is sent.
      </p>

      {gates.map((g) => (
        <div key={g.hex_id} style={{
          background: 'rgba(239,68,68,0.06)',
          border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 'var(--r-inner)', padding: '10px 12px', marginBottom: 10,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <code style={{ fontSize: 11, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{g.hex_id}</code>
            <span style={{ fontSize: 12, color: 'var(--danger)', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
              {g.risk_score?.toFixed(1)}
            </span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
            {g.approvals_count ?? 0}/{g.approvals_required ?? 2} approvals
            {(g.approvals || []).map(a => ` · ${a.operator_id} (${a.role.replace('_', ' ')})`)}
            {g.roles_needed?.length ? ` · need: ${g.roles_needed.map(r => r.replace('_', ' ')).join(', ')}` : ' ✓ all roles covered'}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="Your Operator ID"
              value={opId}
              onChange={(e) => setOpId(e.target.value)}
              className="cir-input"
              style={{ flex: 1, minWidth: 110, padding: '5px 8px', fontSize: 11 }}
            />
            <select value={role} onChange={(e) => setRole(e.target.value)}
                    className="cir-input" style={{ padding: '5px 8px', fontSize: 11 }}>
              <option value="duty_officer">Duty officer</option>
              <option value="district_authority">District authority</option>
            </select>
            <button
              onClick={() => act(g.hex_id, 'approve')}
              disabled={loading && approving === g.hex_id}
              className="cir-btn"
              style={{ padding: '5px 12px', fontSize: 11, background: 'var(--danger)', color: 'var(--cloud)' }}
            >
              {loading && approving === g.hex_id ? 'Working…' : 'Approve'}
            </button>
            <button
              onClick={() => act(g.hex_id, 'reject')}
              disabled={loading && approving === g.hex_id}
              className="cir-btn"
              style={{ padding: '5px 12px', fontSize: 11 }}
            >
              Reject
            </button>
          </div>
        </div>
      ))}

      {result && (
        <div style={{
          padding: '6px 10px', borderRadius: 'var(--r-xs)', fontSize: 11, marginTop: 4,
          background: result.success ? 'var(--success-soft)' : 'var(--danger-soft)',
          border: `1px solid ${result.success ? 'rgba(16,185,129,0.35)' : 'rgba(239,68,68,0.35)'}`,
          color: result.success ? 'var(--success)' : 'var(--danger)',
        }}>
          {result.message}
        </div>
      )}
    </div>
  );
}
