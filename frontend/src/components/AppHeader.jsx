/**
 * AppHeader.jsx — Command-instrument header strip (Final.md §13.4)
 *
 * Contains:
 *  - HydraSense hex brand mark
 *  - Dynamically-resolved chain-of-command breadcrumb (§13.2)
 *  - Region Selector (all 10 onboarded regions) & Location Search Bar (§6, §14.2)
 *  - Deliberate IoT sensor failure demonstration button (§14.5)
 *  - Live clock + situation-status pill
 *  - Two-person [AUTH] gate indicator (§12.4)
 *  - Role switcher (Decision Authority / Response Unit)
 *  - ? legend modal toggle
 *  - Cold-start indicator
 *  - Hairline loading bar on region resolution
 */
import React, { useState, useEffect } from 'react';

const ROLES = ['Decision Authority', 'Response Unit'];

export const ONBOARDED_REGIONS = [
  { code: 'wayanad-kl',     name: 'Wayanad, Kerala (Pilot)',      state: 'Kerala',           district: 'Wayanad' },
  { code: 'idukki-kl',      name: 'Idukki, Kerala',               state: 'Kerala',           district: 'Idukki' },
  { code: 'nilgiris-tn',    name: 'Nilgiris, Tamil Nadu',         state: 'Tamil Nadu',       district: 'Nilgiris' },
  { code: 'rudraprayag-uk', name: 'Rudraprayag, Uttarakhand',     state: 'Uttarakhand',      district: 'Rudraprayag' },
  { code: 'chamoli-uk',     name: 'Chamoli, Uttarakhand',         state: 'Uttarakhand',      district: 'Chamoli' },
  { code: 'kullu-hp',       name: 'Kullu, Himachal Pradesh',      state: 'Himachal Pradesh', district: 'Kullu' },
  { code: 'mangan-sk',      name: 'Mangan, Sikkim',               state: 'Sikkim',           district: 'Mangan' },
  { code: 'darjeeling-wb',  name: 'Darjeeling, West Bengal',      state: 'West Bengal',      district: 'Darjeeling' },
  { code: 'ribhoi-ml',      name: 'Ri-Bhoi, Meghalaya',           state: 'Meghalaya',        district: 'Ri-Bhoi' },
  { code: 'dhemaji-as',     name: 'Dhemaji, Assam',               state: 'Assam',            district: 'Dhemaji' },
];

const LEGEND = [
  { label: 'Green',  desc: '0–29 — Low modeled risk, monitor',      color: '#22c55e' },
  { label: 'Yellow', desc: '30–54 — Elevated / prepare',            color: '#eab308' },
  { label: 'Orange', desc: '55–74 — Significant risk / act',         color: '#f97316' },
  { label: 'Red',    desc: '75–100 — High risk / alert workflow',    color: '#ef4444' },
  { label: 'AUTH',   desc: 'Pending 2-person gate authorization',    color: '#a78bfa' },
  { label: 'PERSISTENT', desc: 'Sustained ≥2 consecutive alarm cycles', color: '#f97316' },
  { label: 'COLD-START', desc: 'First cycle — alerts suppressed until pipeline warms', color: '#60a5fa' },
  { label: 'DESATURATED', desc: 'Reduced saturation: uncalibrated region or wide geotechnical band', color: '#8b949e' },
  { label: 'HOLLOW DOT', desc: 'No local IoT alert coverage (Layer 3 digital-only)', color: '#60a5fa' },
];

export default function AppHeader({
  pendingGates = 0,
  coldStart = false,
  region = null,
  selectedRegionCode = 'wayanad-kl',
  onRegionChange,
  onResolveQuery,
  isResolving = false,
  iotOffline = false,
  onToggleIoT,
  onRoleChange,
}) {
  const [clock, setClock]           = useState('');
  const [role, setRole]             = useState(ROLES[0]);
  const [showLegend, setLegend]     = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [theme, setTheme]           = useState(() => localStorage.getItem('hs-theme') || 'light');

  // Theme effect: set data-theme attribute on <html> element per Cirrus design system
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('hs-theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  // Live clock
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setClock(now.toLocaleTimeString('en-IN', { hour12: false }));
    };
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, []);

  // Chain-of-command breadcrumb (§13.2) — resolved from region
  const locTarget = region?.district || region?.region_label || region?.region_code;
  const breadcrumb = locTarget
    ? `India → ${region?.state || 'Kerala'} → ${locTarget}`
    : 'India → Kerala → Wayanad';

  const handleRole = (r) => {
    setRole(r);
    onRoleChange?.(r);
  };

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      onResolveQuery?.(searchQuery.trim());
      setSearchQuery('');
    }
  };

  return (
    <header className="app-header" style={{ position: 'relative' }}>
      {/* Animated loading hairline on region onboarding (§13.4) */}
      {isResolving && (
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 2,
          background: 'linear-gradient(90deg, transparent, #38bdf8, transparent)',
          backgroundSize: '200% 100%',
          animation: 'hairlineLoad 1.2s infinite linear',
          zIndex: 9999,
        }} />
      )}

      {/* Brand mark — H3 hex SVG (§13.4) */}
      <div className="header-brand">
        <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
          <polygon
            points="14,2 25,8 25,20 14,26 3,20 3,8"
            fill="none" stroke="#38bdf8" strokeWidth="2"
          />
          <polygon
            points="14,7 20,10.5 20,17.5 14,21 8,17.5 8,10.5"
            fill="#38bdf8" opacity="0.3"
          />
        </svg>
        <span className="header-brand-name">HydraSense</span>
      </div>

      {/* Chain-of-command breadcrumb */}
      <div className="header-breadcrumb">{breadcrumb}</div>

      {/* ── Region Selector Dropdown (§6, §14.3) ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 8 }}>
        <select
          value={selectedRegionCode}
          onChange={(e) => onRegionChange?.(e.target.value)}
          className="header-region-select"
          title="Switch Onboarded Region (§14.3 Demo Shortlist)"
        >
          {ONBOARDED_REGIONS.map((r) => (
            <option key={r.code} value={r.code}>
              📍 {r.name}
            </option>
          ))}
        </select>

        {/* ── Resolve Any Hilly Location Bar (§6) ── */}
        <form onSubmit={handleSearchSubmit} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <input
            type="text"
            placeholder="Resolve any hill location (e.g. Munnar, Shimla)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            disabled={isResolving}
            className="header-search-input"
          />
          <button
            type="submit"
            disabled={isResolving}
            className="cir-btn cir-btn--accent"
            style={{
              padding: '6px 12px',
              fontSize: 11,
              cursor: isResolving ? 'wait' : 'pointer',
            }}
            title="Trigger Autonomous Region Onboarding Pipeline (§6)"
          >
            {isResolving ? 'Resolving...' : 'Onboard'}
          </button>
        </form>
      </div>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* ── Deliberate IoT Failure Demo Button (§14.5) ── */}
      <button
        onClick={onToggleIoT}
        className={iotOffline ? 'iot-btn-offline' : 'iot-btn-live'}
        title="Toggle deliberate sensor failure to demonstrate live fallback to satellite/forecast (Final.md §14.5)"
      >
        <span style={{ fontSize: 13 }}>{iotOffline ? '⚡' : '📡'}</span>
        <span>{iotOffline ? 'IoT Offline (Fallback Active)' : 'Simulate IoT Failure'}</span>
      </button>

      {/* Cold-start pill */}
      {coldStart && (
        <div className="header-pill cold-start-pill">
          COLD-START
        </div>
      )}

      {/* Situation status */}
      <div className="header-clock">
        <span className="header-clock-time">{clock}</span>
      </div>

      {/* [AUTH] gate indicator */}
      {pendingGates > 0 && (
        <div className="header-pill auth-pill">
          [AUTH] {pendingGates} pending
        </div>
      )}

      {/* Role switcher */}
      <div className="cir-tabs" style={{ flexShrink: 0 }}>
        {ROLES.map(r => (
          <div
            key={r}
            className={`cir-tab${role === r ? ' is-active' : ''}`}
            onClick={() => handleRole(r)}
          >
            {r === 'Decision Authority' ? 'DA' : 'RU'}
          </div>
        ))}
      </div>

      {/* Light / Dark theme toggle (§13.3 / Cirrus Design System) */}
      <button
        className="header-legend-btn"
        onClick={toggleTheme}
        title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} theme`}
        style={{ minWidth: 32 }}
      >
        {theme === 'dark' ? '☀️' : '🌙'}
      </button>

      {/* ? legend toggle */}
      <button className="header-legend-btn" onClick={() => setLegend(l => !l)} title="Legend">
        ?
      </button>

      {/* Greyed National View tab (§13.4 — Phase 2, not built) */}
      <button className="header-tab-disabled" disabled title="Phase 2 roadmap">
        National View
      </button>

      {/* Legend modal */}
      {showLegend && (
        <div className="legend-modal" onClick={() => setLegend(false)}>
          <div className="legend-box" onClick={e => e.stopPropagation()}>
            <div className="legend-title">
              Tier & Symbol Legend
              <button onClick={() => setLegend(false)} className="legend-close">✕</button>
            </div>
            {LEGEND.map(({ label, desc, color }) => (
              <div key={label} className="legend-row">
                <span className="legend-swatch" style={{ background: color }} />
                <span className="legend-label">{label}</span>
                <span className="legend-desc">{desc}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </header>
  );
}
