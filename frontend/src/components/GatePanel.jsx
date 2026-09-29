/**
 * GatePanel.jsx — Two-Person Red Alert Gate UI (Stage 6 / Final.md §17.4)
 *
 * Polls GET /alert/gate/pending every 5s.
 * Shows a prominent red alert for each pending Red gate.
 * Second operator enters their ID and clicks Approve to fire the CAP.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { getPendingGates, approveGate } from '../api/client';

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

  const handleApprove = async (hexId) => {
    if (!opId.trim()) {
      setResult({ success: false, message: 'Enter your operator ID first.' });
      return;
    }
    setLoading(true);
    setApproving(hexId);
    try {
      const res = await approveGate(hexId, opId.trim());
      setResult({ success: true, message: `Approved by ${res.operator_id}. CAP fires next cycle.` });
      fetchGates();
    } catch (e) {
      const msg = e?.response?.data?.detail || 'Approval failed.';
      setResult({ success: false, message: msg });
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
        The following hex(es) have a sustained Red tier alert waiting for a second-operator
        approval before the CAP notification is sent.
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
            Expires in {10} min
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              type="text"
              placeholder="Your Operator ID"
              value={opId}
              onChange={(e) => setOpId(e.target.value)}
              style={{
                flex: 1, padding: '5px 8px', fontSize: 11,
                background: 'rgba(22,27,34,0.8)',
                border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3',
              }}
            />
            <button
              onClick={() => handleApprove(g.hex_id)}
              disabled={loading && approving === g.hex_id}
              style={{
                padding: '5px 12px', fontSize: 11, fontWeight: 700,
                background: loading && approving === g.hex_id
                  ? 'rgba(239,68,68,0.3)' : '#ef4444',
                border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer',
              }}
            >
              {loading && approving === g.hex_id ? 'Approving…' : 'Approve'}
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
