/**
 * CitizenPreviewPanel.jsx — SACHET/CAP payload preview (Final.md §13.7)
 *
 * "A small, captioned illustrative panel inside the Decision Authority
 * console only — never a built or demoed standalone citizen product."
 *
 * Inverted to light surface (§13.7: outdoor/daylight legibility).
 * Shows how the CAP payload would render once delivered through SACHET /
 * Cell Broadcast — includes Cell Broadcast channel (§12.6).
 */
import React from 'react';

const TIER_BG = {
  Green:  '#dcfce7',
  Yellow: '#fef9c3',
  Orange: '#ffedd5',
  Red:    '#fee2e2',
};
const TIER_BORDER = {
  Green:  '#16a34a',
  Yellow: '#ca8a04',
  Orange: '#ea580c',
  Red:    '#dc2626',
};
const TIER_ICON = {
  Green: '✅', Yellow: '⚠️', Orange: '🔶', Red: '🚨',
};

export default function CitizenPreviewPanel({ selectedHex = null, region = null }) {
  if (!selectedHex) return null;

  const tier   = selectedHex.tier || 'Green';
  const risk   = selectedHex.risk_score?.toFixed(0) ?? '—';
  const lead   = selectedHex.lead_time_min
    ? `~${selectedHex.lead_time_min} min`
    : 'No RED crossing in forecast window';

  const regionLabel = region?.region_label || region?.region_code || 'Unknown region';
  const timeStr = new Date().toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' });

  return (
    <div className="citizen-preview-panel">
      <div className="citizen-preview-caption">
        ↓ SACHET / Cell Broadcast preview (illustrative — §13.7)
      </div>

      {/* Light-inverted surface for daylight legibility */}
      <div
        className="citizen-card"
        style={{
          background: TIER_BG[tier] || '#f9fafb',
          border: `2px solid ${TIER_BORDER[tier] || '#6b7280'}`,
        }}
      >
        <div className="citizen-card-header">
          <span className="citizen-icon">{TIER_ICON[tier]}</span>
          <span className="citizen-tier-label" style={{ color: TIER_BORDER[tier] }}>
            {tier.toUpperCase()} ALERT
          </span>
        </div>

        <div className="citizen-card-body">
          <div className="citizen-region">{regionLabel}</div>
          <div className="citizen-msg">
            {tier === 'Red' || tier === 'Orange'
              ? `Flash flood / landslide risk is HIGH in your area. Move to higher ground or nearest shelter immediately.`
              : tier === 'Yellow'
                ? `Elevated flood/landslide risk. Stay alert and follow local authority instructions.`
                : `Risk is currently low. Continue to monitor official channels.`}
          </div>
          <div className="citizen-meta">
            Risk score: {risk} · Lead time: {lead}
          </div>
          <div className="citizen-timestamp">Preview only · {timeStr} · would need an authorised agency (e.g. SACHET) to send</div>
        </div>

        <div className="citizen-channels">
          <span className="channel-badge">📱 SMS</span>
          <span className="channel-badge">📡 Cell Broadcast</span>
          <span className="channel-badge">🔔 SACHET App</span>
        </div>
      </div>
    </div>
  );
}
