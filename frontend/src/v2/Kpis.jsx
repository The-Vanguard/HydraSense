/**
 * Kpis.jsx — village counts per tier (landslide village value) + peak 24 h rainfall.
 * Counts come from GET /village/summary; unscored villages are reported, never counted as Safe.
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

export default function Kpis({ summary, summaryError, regionStatus, region, national }) {
  const counts = summary?.tier_counts;
  const rows = national ? regionStatus : regionStatus.filter((r) => r.region_code === region);
  const withRain = rows.filter((r) => r.peak_rainfall_24h_mm != null);
  const peak = withRain.length ? withRain.reduce((a, b) => (b.peak_rainfall_24h_mm > a.peak_rainfall_24h_mm ? b : a)) : null;
  const word = rainWord(peak?.peak_rainfall_24h_mm);

  return (
    <div className="hs2-kpis">
      {CARDS.map(({ tier, cls, icon }) => (
        <div key={tier} className={`hs2-kpi ${cls}`}>
          <div className="icon">{icon}</div>
          <div>
            <div className="label">{TIER_WORD[tier]} risk <span className="faint">({tier})</span></div>
            <div className="value num">{counts ? counts[tier] : '—'} <span className="note">villages</span></div>
            <div className="note">
              {summaryError ? 'village summary unavailable'
                : !summary ? 'loading…'
                : `of ${summary.scored_villages} scored · ${summary.unscored_villages} not scored`}
            </div>
          </div>
        </div>
      ))}
      <div className="hs2-kpi blue">
        <div className="icon">☂</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="label">Peak 24 h rainfall</div>
          <div className="value num">{peak ? `${peak.peak_rainfall_24h_mm} mm` : '—'}</div>
          <div className="note">
            {peak ? `${word} · ${peak.region_code} · from the latest scores`
              : 'not stored yet: appears after the next scoring cycle'}
          </div>
        </div>
        {peak && peak.peak_rainfall_24h_mm >= 64.5 && <span className="hs2-tag warn">IMD {word.toLowerCase()}</span>}
      </div>
    </div>
  );
}
