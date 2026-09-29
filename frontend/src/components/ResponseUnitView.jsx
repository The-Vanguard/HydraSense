/**
 * ResponseUnitView.jsx — Field-team interface (Final.md §13.5)
 *
 * "A genuinely narrower interface, since a field team consumes a decision
 * rather than making one."
 *
 * - Chain-of-command breadcrumb collapsed to their own position
 * - No authorization controls, read-only gate confirmation
 * - No FS/feature-contribution explainability stack
 * - IAP appears read-only as assigned tasks (team, ward, route, ETA)
 * - Large touch targets for standing field use
 * - Last-received IAP + map state persists locally (localStorage)
 */
import React, { useEffect, useState } from 'react';
import DeckHexMap from './DeckHexMap';

const TIER_COLOR = {
  Green: '#22c55e', Yellow: '#eab308', Orange: '#f97316', Red: '#ef4444',
};

function loadLocalIAP() {
  try { return JSON.parse(localStorage.getItem('hs_iap_cache') || 'null'); }
  catch { return null; }
}

export default function ResponseUnitView({ hexes = [], alerts = [], region = null }) {
  const [iap, setIap]           = useState(loadLocalIAP);
  const [selectedHex, setSel]   = useState(null);

  // Persist IAP locally on change (§13.5: remains readable if connectivity drops)
  useEffect(() => {
    if (iap) localStorage.setItem('hs_iap_cache', JSON.stringify(iap));
  }, [iap]);

  const redHexes  = hexes.filter(h => h.tier === 'Red');
  const crumbPos  = region ? `Response Unit · ${region.region_label || region.region_code}` : 'Response Unit';

  return (
    <div className="ru-view">
      {/* Header — collapsed breadcrumb */}
      <div className="ru-header">
        <div className="ru-breadcrumb">{crumbPos}</div>
        <div className="ru-live-pill">LIVE</div>
      </div>

      <div className="ru-body">
        {/* Left: assigned tasks */}
        <aside className="ru-tasks">
          <div className="ru-section-title">ASSIGNED TASKS</div>

          {alerts.length === 0 && (
            <div className="ru-empty">No active assignments</div>
          )}

          {alerts.map((a, i) => (
            <div key={i} className="ru-task-card"
                 style={{ borderLeft: `4px solid ${TIER_COLOR[a.tier] || '#484f58'}` }}>
              <div className="ru-task-tier" style={{ color: TIER_COLOR[a.tier] }}>
                {a.tier}
              </div>
              <div className="ru-task-hex">{a.hex_id}</div>
              {a.ward  && <div className="ru-task-detail">Ward: {a.ward}</div>}
              {a.route && <div className="ru-task-detail">Route: {a.route}</div>}
              {a.eta   && <div className="ru-task-detail">ETA: {a.eta}</div>}
              <div className="ru-auth-note">
                {a.authorized_by
                  ? `✓ Auth by ${a.authorized_by}`
                  : 'Pending authorization'}
              </div>
            </div>
          ))}

          {/* IAP read-only */}
          {iap && (
            <div className="ru-iap-section">
              <div className="ru-section-title" style={{ marginTop: 16 }}>INCIDENT ACTION PLAN</div>
              <div className="ru-iap-content">{iap.summary || 'No summary available'}</div>
              <div className="ru-iap-ts">Last updated: {iap.updated_at || '—'}</div>
            </div>
          )}
        </aside>

        {/* Right: map (large touch targets) */}
        <div className="ru-map">
          <DeckHexMap
            hexes={hexes}
            selectedHexId={selectedHex}
            onSelectHex={setSel}
          />
          {/* High-risk hex callout */}
          {redHexes.length > 0 && (
            <div className="ru-red-callout">
              🚨 {redHexes.length} RED hex{redHexes.length > 1 ? 'es' : ''} active
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
