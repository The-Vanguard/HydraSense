/**
 * HazardToggle.jsx — Three-way hazard mode selector (Final.md §13.4)
 *
 * Compound / Flood / Landslide
 * Compound: shows higher of the two tiers per hex (never a blended average).
 * When flood ≠ landslide tier, a dual-tier edge indicator shows on hover.
 */
import React from 'react';

const MODES = [
  { key: 'compound',  label: 'Compound',  icon: '⬡' },
  { key: 'flood',     label: 'Flood',     icon: '🌊' },
  { key: 'landslide', label: 'Landslide', icon: '⛰' },
];

export default function HazardToggle({ mode = 'compound', onChange }) {
  return (
    <div className="cir-tabs" style={{ background: 'var(--bg-card)' }}>
      {MODES.map(m => (
        <div
          key={m.key}
          className={`cir-tab${mode === m.key ? ' is-active' : ''}`}
          onClick={() => onChange?.(m.key)}
          title={m.label}
          style={{ display: 'flex', alignItems: 'center', gap: 4 }}
        >
          <span className="hazard-icon">{m.icon}</span>
          <span className="hazard-label">{m.label}</span>
        </div>
      ))}
    </div>
  );
}
