/**
 * InundationView.jsx — Phase 12
 * Simplified 2D inundation view.
 * SRS §15: Only renders when tier >= Orange — gate is in CODE, not just CSS.
 * Data from GET /risk/{hex_id}/inundation.
 */
import React from 'react';

const ALLOWED_TIERS = new Set(['Orange', 'Red']);

export default function InundationView({ tier, inundation }) {
  // Code-level gate — not CSS visibility
  if (!ALLOWED_TIERS.has(tier)) return null;

  const borderColor = tier === 'Red' ? '#ef4444' : '#f97316';

  return (
    <div className="panel">
      <div className="panel-title">
        Simplified Inundation Estimate
        <span style={{ marginLeft: 6, fontSize: 10, color: '#8b949e', textTransform: 'none', fontWeight: 400 }}>
          — static DEM-derived, not hydraulic model
        </span>
      </div>

      {inundation ? (
        <>
          <div
            className="inundation-placeholder"
            style={{ borderColor, background: `repeating-linear-gradient(45deg, ${borderColor}12 0px, ${borderColor}12 8px, transparent 8px, transparent 16px)` }}
          >
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: borderColor }}>
                ~{inundation.inundation_depth_m}m
              </div>
              <div style={{ fontSize: 10, color: '#8b949e', marginTop: 2 }}>
                est. depth · {inundation.area_ha} ha affected
              </div>
            </div>
          </div>
          <div style={{ fontSize: 10, color: '#484f58', marginTop: 6 }}>
            {inundation.note}
          </div>
        </>
      ) : (
        <div className="inundation-placeholder">
          <span>Loading inundation data…</span>
        </div>
      )}
    </div>
  );
}
