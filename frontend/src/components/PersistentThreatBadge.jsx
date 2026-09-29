/**
 * PersistentThreatBadge.jsx — Stage 6 / Final.md §17.3
 *
 * Shown in the selected-hex header when the hex has been in
 * Orange or Red for ≥2 consecutive ingestion cycles.
 * Also driven by WebSocket "persist_declared" events.
 */
import React from 'react';

export default function PersistentThreatBadge({ declared, cycles, tier }) {
  if (!declared) return null;

  const color = tier === 'Red' ? '#ef4444' : '#f97316';

  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: `${color}18`,
      border: `1px solid ${color}55`,
      borderRadius: 20, padding: '3px 10px',
      fontSize: 10, fontWeight: 700, color,
      animation: 'persistPulse 1.4s ease-in-out infinite',
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: '50%',
        background: color,
        boxShadow: `0 0 6px ${color}`,
        display: 'inline-block',
      }} />
      PERSISTENT THREAT · {cycles} cycles
    </div>
  );
}
