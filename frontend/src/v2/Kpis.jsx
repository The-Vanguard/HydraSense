/**
 * Kpis.jsx — risk counts that always match the map.
 *
 * Everything comes from ONE response (GET /alert/gate/region-status), built from the same latest-score-per-hex
 * rows the map draws.  Villages: each scored map cell belongs to a village (the one it lies in, or the nearest
 * one); a village takes the worst tier among its scored cells.  The cell count is shown under it so the cards
 * add up to what is on the map.
 */
import React from 'react';
import { TIER_WORD } from './tiers';

// IMD 24 h rainfall categories (mm)
const rainWord = (mm) => (mm == null ? null : mm >= 204.5 ? 'Extremely heavy' : mm >= 115.6 ? 'Very heavy'
  : mm >= 64.5 ? 'Heavy' : mm >= 15.6 ? 'Moderate' : mm >= 2.5 ? 'Light' : 'Very light / none');

const CARDS = [
  { tier: 'Red', cls: 'red', icon: '▲' },
  { tier: 'Orange', cls: 'orange', icon: '!' },
  { tier: 'Yellow', cls: 'yellow', icon: '◉' },
  { tier: 'Green', cls: 'green', icon: '✓' },
];
const sum = (rows, key, t) => rows.reduce((a, r) => a + ((r[key] || {})[t] || 0), 0);

export default function Kpis({ regionStatus, region, national }) {
  const rows = national ? regionStatus : regionStatus.filter((r) => r.region_code === region);
  const loaded = regionStatus.length > 0;
  const cells = rows.reduce((a, r) => a + (r.scored_hexes || 0), 0);
  const withRain = rows.filter((r) => r.peak_rainfall_24h_mm != null);
  const peak = withRain.length ? withRain.reduce((a, b) => (b.peak_rainfall_24h_mm > a.peak_rainfall_24h_mm ? b : a)) : null;
  const word = rainWord(peak?.peak_rainfall_24h_mm);

  return (
    <div className="hs2-kpis">
      {CARDS.map(({ tier, cls, icon }) => {
        const v = sum(rows, 'village_tier_counts', tier);
        const c = sum(rows, 'tier_counts', tier);
        return (
          <div key={tier} className={`hs2-kpi ${cls}`}>
            <div className="icon">{icon}</div>
            <div>
              <div className="label">{TIER_WORD[tier]} risk <span className="faint">({tier})</span></div>
              <div className="value num">{loaded ? v : '—'} <span className="note">villages</span></div>
              <div className="note">{loaded ? `${c} of ${cells} map cells` : 'loading…'}</div>
            </div>
          </div>
        );
      })}
      <div className="hs2-kpi blue">
        <div className="icon">☂</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="label">Peak 24 h rainfall</div>
          <div className="value num">{peak ? `${peak.peak_rainfall_24h_mm} mm` : '—'}</div>
          <div className="note">
            {peak ? `${word}${national ? ` · ${peak.region_code}` : ''} · highest of the scored cells`
              : loaded ? 'not stored yet: appears after the next scoring cycle' : 'loading…'}
          </div>
        </div>
        {peak && peak.peak_rainfall_24h_mm >= 64.5 && <span className="hs2-tag warn">IMD {word.toLowerCase()}</span>}
      </div>
    </div>
  );
}
