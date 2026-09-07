/**
 * AlertFeed.jsx — Phase 12
 * Polls GET /alert/feed every 10s.
 * CAP alerts and downgrade events rendered as DISTINCT item types (SRS §17).
 * Auto-fires a CAP entry on Orange/Red, followed by a downgrade after 8s.
 */
import React, { useEffect, useState, useRef } from 'react';
import { getAlertFeed } from '../api/client';

const POLL_MS = 10_000;

function formatTime(ts) {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return ''; }
}

function AlertItem({ item }) {
  const isDowngrade = item.type === 'downgrade';
  const tierClass   = !isDowngrade && item.tier === 'Red' ? 'cap Red' : 'cap';
  return (
    <div className={`alert-item ${isDowngrade ? 'downgrade' : tierClass}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          {isDowngrade ? (
            <span style={{ fontSize: 10, fontWeight: 600, color: '#8b949e', textTransform: 'uppercase' }}>
              ↓ Downgrade
            </span>
          ) : (
            <span style={{
              fontSize: 10, fontWeight: 700,
              color: item.tier === 'Red' ? '#ef4444' : '#f97316',
              textTransform: 'uppercase',
            }}>
              ⚠ CAP Alert — {item.tier}
            </span>
          )}
          <div style={{ marginTop: 3, fontSize: 12 }}>{item.message}</div>
          <div style={{ marginTop: 2, fontSize: 10, color: '#484f58', fontFamily: 'monospace' }}>
            {item.hex_id}
          </div>
        </div>
        <div style={{ fontSize: 10, color: '#484f58', flexShrink: 0, marginLeft: 8 }}>
          {formatTime(item.timestamp)}
        </div>
      </div>
      {!isDowngrade && item.nearest_shelter && (
        <div style={{ marginTop: 4, fontSize: 10, color: '#8b949e' }}>
          Nearest shelter: {item.nearest_shelter.name} ({(item.nearest_shelter.distance_m / 1000).toFixed(1)} km)
        </div>
      )}
      {!isDowngrade && item.lead_time_min && (
        <div style={{ marginTop: 2, fontSize: 10, color: '#f97316' }}>
          Lead time: {Math.floor(item.lead_time_min / 60)}h {item.lead_time_min % 60}min
        </div>
      )}
    </div>
  );
}

export default function AlertFeed({ customAlert }) {
  const [alerts,    setAlerts]    = useState([]);
  const [localCap,  setLocalCap]  = useState(null);
  const [downgrade, setDowngrade] = useState(null);
  const timerRef     = useRef(null);
  const downgradeRef = useRef(null);
  const prevTierRef  = useRef(null);

  const fetchAlerts = () => {
    getAlertFeed().then(setAlerts).catch(() => {});
  };

  useEffect(() => {
    fetchAlerts();
    timerRef.current = setInterval(fetchAlerts, POLL_MS);
    return () => clearInterval(timerRef.current);
  }, []);

  // Auto-fire CAP when customAlert is Orange/Red, then downgrade after 8s
  useEffect(() => {
    clearTimeout(downgradeRef.current);
    if (!customAlert) {
      setLocalCap(null); setDowngrade(null); prevTierRef.current = null;
      return;
    }
    const tier = customAlert.tier;
    if (['Orange', 'Red'].includes(tier) && tier !== prevTierRef.current) {
      setLocalCap({ ...customAlert, timestamp: new Date().toISOString() });
      setDowngrade(null);
      prevTierRef.current = tier;
      downgradeRef.current = setTimeout(() => {
        setDowngrade({
          type: 'downgrade',
          hex_id: customAlert.hex_id,
          message: 'Risk subsiding — consecutive below-Orange cycles >= 2',
          timestamp: new Date().toISOString(),
        });
      }, 8000);
    }
    return () => clearTimeout(downgradeRef.current);
  }, [customAlert]);

  const combined = [...alerts];
  if (downgrade) combined.push(downgrade);
  if (localCap)  combined.push(localCap);

  return (
    <div className="panel">
      <div className="panel-title">
        Alert Feed
        <span style={{ marginLeft: 6, fontSize: 9, color: '#484f58', textTransform: 'none', fontWeight: 400 }}>
          — polls every {POLL_MS / 1000}s
        </span>
      </div>
      {combined.length === 0 ? (
        <div className="empty-state">No alerts — system nominal</div>
      ) : (
        [...combined].reverse().map((a, idx) => (
          <AlertItem key={a.alert_id || `local_${idx}`} item={a} />
        ))
      )}
    </div>
  );
}
