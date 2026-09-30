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

export default function GatePanel() {
  const [gates,      setGates]      = useState([]);
  const [opId,       setOpId]       = useState('');
  const [approving,  setApproving]  = useState(null);   // hex_id being approved
  const [result,     setResult]     = useState(null);   // {success, message}
  const [loading,    setLoading]    = useState(false);

  const fetchGates = useCallback(() => {
    getPendingGates()
      .then((data) => setGates(data.pending_gates || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchGates();
    const iv = setInterval(fetchGates, POLL_MS);
    return () => clearInterval(iv);
  }, [fetchGates]);

  const [role, setRole] = useState('duty_officer');

  const act = async (hexId, kind) => {
    if (!opId.trim()) {
      setResult({ success: false, message: 'Enter your operator ID first.' });
      return;
    }
    setLoading(true);
    setApproving(hexId);
    try {
      if (kind === 'reject') {
        await rejectGate(hexId, opId.trim(), role, 'rejected from dashboard');
        setResult({ success: true, message: 'Alert rejected. Nothing was sent.' });
      } else {
        const res = await approveGate(hexId, opId.trim(), role);
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

  if (gates.length === 0) return null;   // hide panel when nothing pending

  return (
    <div className="panel gate-panel">
      <div className="panel-title" style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16 }}>🔴</span>
        <span>Red Alert — Awaiting Gate Approval</span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: '#8b949e', fontWeight: 400 }}>
          Final.md §17.4
        </span>
      </div>

      <p style={{ fontSize: 11, color: '#f87171', marginBottom: 10, lineHeight: 1.5 }}>
        These alerts need approval from two different people (duty officer and district
        authority) before anything is sent. Operator ID and role are self-declared: there is no
        login yet.
      </p>

      {gates.map((g) => (
        <div key={g.hex_id} style={{
          background: 'rgba(239,68,68,0.08)',
          border: '1px solid rgba(239,68,68,0.3)',
          borderRadius: 6, padding: '10px 12px', marginBottom: 10,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <code style={{ fontSize: 11, color: '#e6edf3' }}>{g.hex_id}</code>
            <span style={{ fontSize: 11, color: '#f87171', fontWeight: 700 }}>
              Risk: {g.risk_score?.toFixed(1)}
            </span>
          </div>
          <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 8 }}>
            Created: {g.created_at ? new Date(g.created_at).toLocaleTimeString() : '—'} ·
            Expires 10 min after creation
          </div>
          <div style={{ fontSize: 11, color: '#e6edf3', marginBottom: 6 }}>
            Approvals {g.approvals_count ?? 0}/{g.approvals_required ?? 2}
            {(g.approvals || []).map((a) => ` · ${a.operator_id} (${a.role.replace('_', ' ')})`)}
            {g.roles_needed?.length ? ` · waiting for: ${g.roles_needed.map((r) => r.replace('_', ' ')).join(', ')}` : ''}
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
          padding: '6px 10px', borderRadius: 4, fontSize: 11, marginTop: 4,
          background: result.success ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
          border: `1px solid ${result.success ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'}`,
          color: result.success ? '#4ade80' : '#f87171',
        }}>
          {result.message}
        </div>
      )}
    </div>
  );
}
