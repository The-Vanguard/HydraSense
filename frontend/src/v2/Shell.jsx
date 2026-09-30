/**
 * Shell.jsx — top bar and footer of the v2 dashboard.
 */
import React, { useEffect, useState } from 'react';
import { fmtIST } from './tiers';

export const TABS = [
  { key: 'overview', label: 'Dashboard Overview', icon: '▦' },
  { key: 'map', label: 'GIS Risk Map', icon: '⌖' },
  { key: 'alerts', label: 'Alerts', icon: '🔔' },
  { key: 'replay', label: 'Event Replay', icon: '⏵' },
  { key: 'analytics', label: 'Analytics', icon: '▥' },
];

function Logo() {
  return (
    <svg width="40" height="34" viewBox="0 0 40 34" aria-hidden="true">
      <path d="M2 28 L14 8 L21 18 L26 12 L38 28 Z" fill="#1d4ed8" />
      <path d="M2 30 Q8 25 14 30 T26 30 T38 30" stroke="#38bdf8" strokeWidth="2.4" fill="none" />
    </svg>
  );
}

export function TopBar({ tab, onTab, alertCount, backendUp, liveScores, lastUpdated, role, onRole }) {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('hs-theme') || 'light'; } catch { return 'light'; }
  });
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('hs-theme', theme); } catch { /* ignore */ }
  }, [theme]);

  return (
    <header className="hs2-top">
      <div className="hs2-brand">
        <Logo />
        <div>
          <div className="hs2-brand-title">HydraSense<small>v2</small></div>
          <div className="hs2-brand-sub">Flash Flood &amp; Landslide Early Warning</div>
        </div>
      </div>
      <nav className="hs2-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`hs2-tab${tab === t.key ? ' is-active' : ''}`} onClick={() => onTab(t.key)}>
            <span className="ico" aria-hidden="true">{t.icon}</span>{t.label}
            {t.key === 'alerts' && alertCount > 0 && <span className="hs2-badge">{alertCount}</span>}
          </button>
        ))}
      </nav>
      <div className="hs2-top-right">
        <span className={`hs2-pill ${liveScores ? 'ok' : 'warn'}`}
              title={`Last updated: ${fmtIST(lastUpdated)} (live = newest score under 20 min old)`}>
          <span className="hs2-dot" />{liveScores ? 'Live' : 'Not current'}
        </span>
        <span className={`hs2-pill ${backendUp === false ? 'bad' : backendUp ? 'ok' : ''}`}>
          <span className="hs2-dot" />{backendUp === false ? 'Offline' : backendUp ? 'Online' : 'Connecting…'}
        </span>
        <select className="hs2-select" value={role} onChange={(e) => onRole(e.target.value)} aria-label="Role">
          <option>Decision Authority</option>
          <option>Response Unit</option>
        </select>
        <button className="hs2-iconbtn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? '☀' : '☾'}</button>
      </div>
    </header>
  );
}

export function Footer({ rainSource }) {
  const rain = !rainSource ? 'no current scores' : /live/.test(rainSource) ? 'live' : rainSource === 'sensor' ? 'simulated' : 'cached / fallback';
  return (
    <footer className="hs2-footer">
      <span>DEM: SRTM (static, onboarding)</span>
      <span>Land cover: ESA WorldCover (static)</span>
      <span>Soil: SoilGrids (static)</span>
      <span>Rainfall: {rain}{rainSource ? ` (${rainSource})` : ''}</span>
      <span>Sensors: none deployed</span>
      <span style={{ marginLeft: 'auto' }}>Scoring: physics-first index (uncalibrated) · HydraSense SIH prototype</span>
    </footer>
  );
}
