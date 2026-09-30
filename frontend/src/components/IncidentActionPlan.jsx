/**
 * IncidentActionPlan.jsx — Incident Action Plan (IAP) Panel
 * Final.md §13.4: "an editable Incident Action Plan with a dashed 'live document' border"
 * Final.md §13.5: "in Response Unit view, reframed as assigned tasks (team, ward, route, ETA)"
 */
import React, { useState } from 'react';

const INITIAL_ORDERS = [
  { id: 'ORD-101', team: 'NDRF 04 - Special Rescue', task: 'Evacuation corridor setup & riverbank cordon', sector: 'Mundakkai / Chooralmala', eta: '12 min', status: 'En Route', route: 'SH-59 via Meppadi' },
  { id: 'ORD-102', team: 'Kerala Fire & Rescue Squad 2', task: 'Pre-position high-clearance rescue vehicles', sector: 'Chooralmala Bridge', eta: 'On Scene', status: 'Active', route: 'Direct North Access' },
  { id: 'ORD-103', team: 'SDRF Hill Unit 09', task: 'Slope monitor & secondary slide lookout', sector: 'Attamala Ridge', eta: '25 min', status: 'Dispatched', route: 'Attamala Forest Track' },
];

export default function IncidentActionPlan({ readOnly = false, selectedHex = null, region = null }) {
  const [orders, setOrders] = useState(INITIAL_ORDERS);
  const [newTeam, setNewTeam] = useState('');
  const [newTask, setNewTask] = useState('');
  const [isAdding, setIsAdding] = useState(false);

  const regionName = region?.district || region?.region_label || 'Wayanad, Kerala';

  const handleAddOrder = (e) => {
    e.preventDefault();
    if (!newTeam.trim() || !newTask.trim()) return;
    const newOrd = {
      id: `ORD-${Math.floor(100 + Math.random() * 900)}`,
      team: newTeam.trim(),
      task: newTask.trim(),
      sector: selectedHex?.village || `${regionName} Sector`,
      eta: '15 min',
      status: 'Dispatched',
      route: 'Primary Emergency Arterial',
    };
    setOrders([newOrd, ...orders]);
    setNewTeam('');
    setNewTask('');
    setIsAdding(false);
  };

  const handleStatusCycle = (id) => {
    if (readOnly) return;
    setOrders(orders.map(o => {
      if (o.id !== id) return o;
      const nextStatus = o.status === 'Dispatched' ? 'En Route'
        : o.status === 'En Route' ? 'Active'
        : o.status === 'Active' ? 'Completed'
        : 'Dispatched';
      return { ...o, status: nextStatus };
    }));
  };

  return (
    <div className="panel iap-panel" style={{
      margin: '0 12px 10px',
      padding: '12px',
      position: 'relative',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '0.05em', color: 'var(--text-primary)' }}>
            INCIDENT ACTION PLAN (IAP)
          </span>
          <span style={{
            fontSize: 9,
            padding: '1px 5px',
            borderRadius: 3,
            background: 'rgba(46, 125, 239, 0.12)',
            color: 'var(--accent)',
            fontFamily: 'var(--font-mono, monospace)',
          }}>
            ILLUSTRATIVE · SAMPLE TASKS
          </span>
        </div>
        {!readOnly && (
          <button
            onClick={() => setIsAdding(a => !a)}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-xs)',
              color: 'var(--accent)',
              fontSize: 10,
              padding: '2px 8px',
              cursor: 'pointer',
            }}
          >
            {isAdding ? '✕ Cancel' : '+ Dispatch Unit'}
          </button>
        )}
      </div>

      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
        Operational Area: <strong style={{ color: 'var(--text-secondary)' }}>{regionName}</strong>
        {selectedHex?.village && ` · Focus: ${selectedHex.village}`}
      </div>

      {isAdding && !readOnly && (
        <form onSubmit={handleAddOrder} style={{
          marginBottom: 10,
          padding: 8,
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-xs)',
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}>
          <input
            type="text"
            placeholder="Unit / Force (e.g. NDRF Unit 02, SDRF Team)"
            value={newTeam}
            onChange={e => setNewTeam(e.target.value)}
            className="header-search-input"
            style={{ width: '100%' }}
            required
          />
          <input
            type="text"
            placeholder="Operational Directive / Mission Order"
            value={newTask}
            onChange={e => setNewTask(e.target.value)}
            className="cir-input"
            style={{ padding: '6px 10px', fontSize: 11 }}
            required
          />
          <button
            type="submit"
            className="cir-btn cir-btn--accent"
            style={{ padding: '6px 12px', fontSize: 11 }}
          >
            Authorize & Issue Dispatch Order
          </button>
        </form>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {orders.map((ord) => (
          <div
            key={ord.id}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-xs)',
              padding: '6px 8px',
              fontSize: 11,
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{ord.team}</span>
              <span
                onClick={() => handleStatusCycle(ord.id)}
                title={readOnly ? '' : 'Click to cycle status'}
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  fontFamily: 'monospace',
                  padding: '1px 5px',
                  borderRadius: 3,
                  cursor: readOnly ? 'default' : 'pointer',
                  background: ord.status === 'Active' ? 'rgba(16, 185, 129, 0.15)'
                    : ord.status === 'Completed' ? 'rgba(148, 163, 184, 0.15)'
                    : 'rgba(245, 158, 11, 0.15)',
                  color: ord.status === 'Active' ? 'var(--tier-green)'
                    : ord.status === 'Completed' ? 'var(--text-muted)'
                    : 'var(--tier-yellow)',
                  border: `1px solid ${ord.status === 'Active' ? 'rgba(16,185,129,0.3)' : ord.status === 'Completed' ? 'rgba(148,163,184,0.2)' : 'rgba(245,158,11,0.3)'}`,
                }}
              >
                {ord.status}
              </span>
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: 10 }}>{ord.task}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)', fontSize: 9, marginTop: 2 }}>
              <span>Sector: {ord.sector}</span>
              <span>ETA: {ord.eta} · Route: {ord.route}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
