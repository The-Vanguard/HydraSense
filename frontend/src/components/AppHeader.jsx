/**
 * AppHeader.jsx — Disaster Management GIS Portal Header
 * Matches exact reference style from reference.jpeg:
 *  - Left: HydraSense mark + name + subtitle (a student prototype; not affiliated with any government agency)
 *  - Center: Capsule tab bar (Dashboard Overview, Landslide GIS Map [Active], Landslide Alerts [#alerts] with orange high-risk pill)
 *  - Right: "LIVE MONITORING ACTIVE" pill with pulsing dot + Region selector pill + DA/RU role + theme toggle
 */
import React, { useState, useEffect } from 'react';

const ROLES = ['Decision Authority', 'Response Unit'];

export const ONBOARDED_REGIONS = [
  { code: 'all-india',      name: 'India (National Level)',       state: 'All India',        district: 'National' },
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
  { label: 'Green',  desc: '0–29 — Low modeled risk, monitor',      color: '#10b981' },
  { label: 'Yellow', desc: '30–54 — Elevated / prepare',            color: '#f59e0b' },
  { label: 'Orange', desc: '55–74 — Significant risk / act',         color: '#f97316' },
  { label: 'Red',    desc: '75–100 — High risk / alert workflow',    color: '#ef4444' },
  { label: 'AUTH',   desc: 'Pending 2-person gate authorization',    color: '#a78bfa' },
  { label: 'PERSISTENT', desc: 'Sustained ≥2 consecutive alarm cycles', color: '#f97316' },
  { label: 'COLD-START', desc: 'First cycle — alerts suppressed until pipeline warms', color: '#60a5fa' },
];

export default function AppHeader({
  pendingGates = 0,
  coldStart = false,
  authState = null,             // e.g. "AUTH 1/2" mirrored from the backend gate (v2 Sec. 13.3)
  region = null,
  selectedRegionCode = 'wayanad-kl',
  onRegionChange,
  onResolveQuery,
  isResolving = false,
  iotOffline = false,
  onToggleIoT,
  onRoleChange,
  activeTab = 'map',
  onTabChange,
  highRiskCount = 2,
}) {
  const [clock, setClock]             = useState('');
  const [role, setRole]               = useState(ROLES[0]);
  const [showLegend, setLegend]       = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentNav, setCurrentNav]   = useState(activeTab);
  const [theme, setTheme]             = useState(() => localStorage.getItem('hs-theme') || 'light');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('hs-theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setClock(now.toLocaleTimeString('en-IN', { hour12: false }));
    };
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, []);

  const handleRole = (r) => {
    setRole(r);
    onRoleChange?.(r);
  };

  const handleNavClick = (tabKey) => {
    setCurrentNav(tabKey);
    onTabChange?.(tabKey);
  };

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      onResolveQuery?.(searchQuery.trim());
      setSearchQuery('');
    }
  };

  return (
    <header className="ref-app-header">
      {/* Animated loading hairline */}
      {isResolving && (
        <div className="ref-hairline-loader" />
      )}

      {/* ── LEFT: Brand, Title & Subtitle ── */}
      <div className="ref-header-left">
        {/* Shield Icon in Dark Rounded Container */}
        <div className="ref-shield-badge">
          <svg width="18" height="20" viewBox="0 0 24 28" fill="none">
            <path
              d="M12 2L3 6V13C3 19.5 6.8 25.5 12 27C17.2 25.5 21 19.5 21 13V6L12 2Z"
              stroke="#ffffff"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M12 7V17M12 17L9 14M12 17L15 14"
              stroke="#38bdf8"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>

        {/* Title & Subtitle */}
        <div className="ref-title-group">
          <div className="ref-main-title">
            HYDRASENSE
            <span className="ref-title-subbrand"> · FLASH FLOOD &amp; LANDSLIDE EARLY WARNING</span>
          </div>
          <div className="ref-subtitle">
            SIH prototype · decision support for district teams · not an official warning service
          </div>
        </div>
      </div>

      {/* ── CENTER: Pill Capsule Navigation Bar ── */}
      <div className="ref-nav-capsule">
        {/* Dashboard Overview */}
        <button
          className={`ref-capsule-btn${currentNav === 'overview' ? ' is-active' : ''}`}
          onClick={() => handleNavClick('overview')}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="14" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
          </svg>
          <span>Dashboard Overview</span>
        </button>

        {/* Landslide GIS Map (#map) - Active */}
        <button
          className={`ref-capsule-btn${currentNav === 'map' ? ' is-active' : ''}`}
          onClick={() => handleNavClick('map')}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="9" />
            <polyline points="12 7 12 12 15 15" />
          </svg>
          <span>Landslide GIS Map (#map)</span>
        </button>

        {/* Landslide Alerts (#alerts) */}
        <button
          className={`ref-capsule-btn${currentNav === 'alerts' ? ' is-active' : ''}`}
          onClick={() => handleNavClick('alerts')}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          <span>Landslide Alerts (#alerts)</span>
          {/* Orange Risk Pill */}
          <span className="ref-alert-count-pill">
            {pendingGates > 0 ? `${pendingGates} PENDING` : `${highRiskCount} HIGH RISK`}
          </span>
        </button>
      </div>

      {/* ── RIGHT: Live Status, Region Selector, Role & Tools ── */}
      <div className="ref-header-right">
        {/* Two-person authorisation state, mirrored from the backend gate */}
        <div className="ref-live-pill" title="Two-person authorisation (duty officer + district authority)"
             style={authState ? { background: 'rgba(239,68,68,0.15)', color: '#f87171', borderColor: 'rgba(239,68,68,0.4)' } : undefined}>
          <span>{authState || 'AUTH · no pending alert'}</span>
        </div>
        {/* Live Monitoring Active Green Pill */}
        <div className="ref-live-pill">
          <span className="ref-live-pulse-dot" />
          <span>LIVE MONITORING ACTIVE</span>
        </div>

        {/* Region Selector Pill */}
        <div className="ref-region-pill-wrap">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2.5">
            <circle cx="12" cy="12" r="10" />
            <line x1="2" y1="12" x2="22" y2="12" />
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
          <span className="ref-region-label">Region:</span>
          <select
            value={selectedRegionCode}
            onChange={(e) => onRegionChange?.(e.target.value)}
            className="ref-region-dropdown"
          >
            {ONBOARDED_REGIONS.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </div>

        {/* Quick Hill Location Resolver */}
        <form onSubmit={handleSearchSubmit} className="ref-search-form">
          <input
            type="text"
            placeholder="Resolve hill area..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            disabled={isResolving}
            className="ref-search-input"
          />
          <button type="submit" disabled={isResolving} className="ref-search-btn">
            {isResolving ? '...' : 'Go'}
          </button>
        </form>

        {/* Deliberate IoT Failure simulation toggle button */}
        <button
          onClick={onToggleIoT}
          className={`ref-tool-pill ${iotOffline ? 'is-offline' : ''}`}
          title="Toggle IoT Telemetry failure fallback"
        >
          <span>{iotOffline ? '⚡ IoT Fallback' : '📡 IoT Live'}</span>
        </button>

        {/* Role toggle (DA/RU) */}
        <div className="ref-role-pill-group">
          {ROLES.map(r => (
            <button
              key={r}
              className={`ref-role-btn${role === r ? ' is-active' : ''}`}
              onClick={() => handleRole(r)}
              title={r}
            >
              {r === 'Decision Authority' ? 'DA' : 'RU'}
            </button>
          ))}
        </div>

        {/* Light / Dark theme toggle */}
        <button
          className="ref-icon-circle-btn"
          onClick={toggleTheme}
          title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} theme`}
        >
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>

        {/* Legend modal toggle */}
        <button
          className="ref-icon-circle-btn"
          onClick={() => setLegend(l => !l)}
          title="Legend"
        >
          ?
        </button>

        {/* Clock */}
        <div className="ref-header-clock">{clock}</div>
      </div>

      {/* Legend Modal */}
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
