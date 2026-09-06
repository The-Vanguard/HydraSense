/**
 * AlertFeed.jsx — Phase 12
 * Polls GET /alert/feed every 10s.
 * CAP alerts and downgrade events rendered as DISTINCT item types.
 * SRS §17: never conflate the two.
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
          🏫 Nearest shelter: {item.nearest_shelter.name} ({(item.nearest_shelter.distance_m / 1000).toFixed(1)} km)
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
  const [alerts, setAlerts] = useState([]);
  const timerRef = useRef(null);

  const fetchAlerts = () => {
    getAlertFeed()
      .then(setAlerts)
      .catch(() => {}); // silent — don't crash panel on network error
  };

  useEffect(() => {
    fetchAlerts();
    timerRef.current = setInterval(fetchAlerts, POLL_MS);
    return () => clearInterval(timerRef.current);
  }, []);

  const combinedAlerts = [...alerts];
  if (customAlert) {
    // Add custom simulated alert at top
    combinedAlerts.push(customAlert);
  }

  return (
    <div className="panel">
      <div className="panel-title">
        Alert Feed
        <span style={{ marginLeft: 6, fontSize: 9, color: '#484f58', textTransform: 'none', fontWeight: 400 }}>
          — polls every {POLL_MS / 1000}s
        </span>
      </div>

      {combinedAlerts.length === 0 ? (
        <div className="empty-state">No alerts — system nominal</div>
      ) : (
        // Most recent first
        [...combinedAlerts].reverse().map((a, idx) => (
          <AlertItem key={a.alert_id || `sim_${idx}`} item={a} />
        ))
      )}
    </div>
  );
}

