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
    <div className="hazard-toggle">
      {MODES.map(m => (
        <button
          key={m.key}
          className={`hazard-btn${mode === m.key ? ' active' : ''}`}
          onClick={() => onChange?.(m.key)}
          title={m.label}
        >
          <span className="hazard-icon">{m.icon}</span>
          <span className="hazard-label">{m.label}</span>
        </button>
      ))}
    </div>
  );
}
