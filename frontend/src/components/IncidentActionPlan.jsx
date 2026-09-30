/**
 * IncidentActionPlan.jsx — Incident Action Plan (IAP) Panel
 * Final.md §13.4: "an editable Incident Action Plan with a dashed 'live document' border"
 * Final.md §13.5: "in Response Unit view, reframed as assigned tasks (team, ward, route, ETA)"
 */
import React, { useState, useEffect, useRef } from 'react';

// Suggested task TEMPLATES by tier (v2 Sec. 10.4 action text).  They are not real dispatches: no team
// has been assigned, so status is "Suggested" and ETA / route are left for the duty officer to fill in.
const T = (id, team, task, sector) => ({ id, team, task, sector, eta: '—', status: 'Suggested', route: '—' });
const ORDERS_BY_TIER = {
  Red: [
    T('T-1', 'Rescue team (to assign)', 'Evacuate people below steep slopes and along stream banks', 'Red hexes / listed villages'),
    T('T-2', 'Fire & rescue (to assign)', 'Pre-position vehicles outside the hazard zone', 'Nearest safe road junction'),
    T('T-3', 'Local volunteers (to assign)', 'Watch for new cracks, muddy water, sudden stream changes', 'Upslope of the villages'),
  ],
  Orange: [
    T('T-1', 'Revenue / panchayat team (to assign)', 'Precautionary evacuation of low-lying and slope-foot households', 'Orange hexes'),
    T('T-2', 'Panchayat alert team (to assign)', 'Sound sirens and inform village nodal contacts', 'Listed villages'),
  ],
  Yellow: [
    T('T-1', 'District control room', 'Watch rainfall and stream gauges each cycle', 'District'),
    T('T-2', 'Panchayat (to assign)', 'Keep shelters ready (standby only)', 'Nearest shelters'),
  ],
  Green: [
    T('T-1', 'District control room', 'Routine monitoring; no action needed', 'District'),
  ],
};

function getInitialOrders(tier) {
  return (ORDERS_BY_TIER[tier] || ORDERS_BY_TIER.Green).map(o => ({ ...o }));
}

export default function IncidentActionPlan({ readOnly = false, selectedHex = null, region = null }) {
  const tier = selectedHex?.tier || 'Green';
  const [orders, setOrders] = useState(() => getInitialOrders(tier));
  const [newTeam, setNewTeam]   = useState('');
  const [newTask, setNewTask]   = useState('');
  const [isAdding, setIsAdding] = useState(false);
  const prevHexRef = useRef(null);

  // Reset orders whenever the selected hex changes
  useEffect(() => {
    const hexId = selectedHex?.hex_id || null;
    if (hexId !== prevHexRef.current) {
      prevHexRef.current = hexId;
      setOrders(getInitialOrders(selectedHex?.tier || 'Green'));
      setIsAdding(false);
    }
  }, [selectedHex]);

  const regionName = region?.district || region?.region_label || 'selected region';

  const handleAddOrder = (e) => {
    e.preventDefault();
    if (!newTeam.trim() || !newTask.trim()) return;
    const newOrd = {
      id: `T-${orders.length + 1}`,
      team: newTeam.trim(),
      task: newTask.trim(),
      sector: selectedHex?.village || `${regionName} Sector`,
      eta: '—',
      status: 'Added by operator',
      route: '—',
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
    <div className="panel iap-panel" style={{ position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '0.05em', color: 'var(--text-primary)' }}>
            INCIDENT ACTION PLAN (IAP)
          </span>
          <span style={{
            fontSize: 9,
            padding: '1px 6px',
            borderRadius: 'var(--r-pill)',
            background: tier === 'Red'    ? 'var(--danger-soft)'
                      : tier === 'Orange' ? 'var(--orange-soft)'
                      : tier === 'Yellow' ? 'var(--warning-soft)'
                      : 'rgba(46, 125, 239, 0.1)',
            color: tier === 'Red'    ? 'var(--danger)'
                 : tier === 'Orange' ? 'var(--orange)'
                 : tier === 'Yellow' ? 'var(--warning)'
                 : 'var(--accent)',
            fontFamily: 'var(--font-mono)',
            fontWeight: 600,
            border: '1px solid currentColor',
            opacity: 0.8,
          }}>
            ILLUSTRATIVE · {tier.toUpperCase()} TIER TASKS
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
          background: 'var(--sky)',
          border: '1px solid var(--edge)',
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
