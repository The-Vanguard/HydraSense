/**
 * App.jsx — HydraSense Command Dashboard
 * Final.md §13.4 — Three-zone layout:
 *   Header | Body (LeftColumn + CenterMap + RightStack) | Footer
 *
 * Roles (§13.2):
 *   Decision Authority — full console (default)
 *   Response Unit     — ResponseUnitView (narrower, read-only)
 *
 * WebSocket: direct connection to ws://localhost:8000/ws/alerts (§14.6)
 *   - Full state snapshot on connect/reconnect before any delta
 *   - Exponential back-off: 5s → 10s → 20s → 60s (cap)
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';

import {
  getRiskMap, getRisk, getRiskHistory, getInundation, getUncertainty,
  createAlertWebSocket, getLoroResults, approveGate, getConfidenceBreakdown,
  getPersistentThreat, getEventsMap, resolveRegion, toggleIoTSensor,
} from './api/client';

// Layout components (Final.md §13.4)
import AppHeader          from './components/AppHeader';
import AppFooter          from './components/AppFooter';
import LeftColumn         from './components/LeftColumn';
import HazardToggle       from './components/HazardToggle';
import TimeScrubber       from './components/TimeScrubber';
import ResponseUnitView   from './components/ResponseUnitView';
import IncidentActionPlan from './components/IncidentActionPlan';

// Map: deck.gl 3D (primary) + Leaflet 2D (fallback/switchable)
import DeckHexMap from './components/DeckHexMap';
import HexMap     from './components/HexMap';
import ErrorBoundary from './components/ErrorBoundary';

// Right-stack panels
import ConfidenceLeadTime    from './components/ConfidenceLeadTime';
import TrendLine             from './components/TrendLine';
import InundationView        from './components/InundationView';
import FeaturePanel          from './components/FeaturePanel';
import ValidationPanel       from './components/ValidationPanel';
import AlertFeed             from './components/AlertFeed';
import HistoricalEventPanel  from './components/HistoricalEventPanel';
import ManualScenarioPanel   from './components/ManualScenarioPanel';
import GatePanel             from './components/GatePanel';
import LoroPanel             from './components/LoroPanel';
import PersistentThreatBadge from './components/PersistentThreatBadge';
import CitizenPreviewPanel   from './components/CitizenPreviewPanel';
import DataSourceLabel       from './components/DataSourceLabel';
import SensorLabel           from './components/SensorLabel';

const POLL_MS         = 10_000;
const POLL_MS_INITIAL =  3_000;

export default function App() {
  // ── Core state ────────────────────────────────────────────────────────
  const [hexes,         setHexes]         = useState([]);
  const [selectedHexId, setSelectedHexId] = useState(null);
  const [risk,          setRisk]          = useState(null);
  const [history,       setHistory]       = useState([]);
  const [inundation,    setInundation]    = useState(null);
  const [dataSource,    setDataSource]    = useState('live');
  const [demoStage,     setDemoStage]     = useState(null);
  const [persistState,  setPersistState]  = useState({ declared: false, cycles: 0 });
  const [selectedRegionCode, setSelectedRegionCode] = useState('wayanad-kl');
  const [isResolving,        setIsResolving]        = useState(false);
  const [iotOffline,         setIotOffline]         = useState(false);

  // ── Layout / role state ───────────────────────────────────────────────
  const [role,         setRole]         = useState('Decision Authority');
  const [hazardMode,   setHazardMode]   = useState('compound');   // §13.4
  const [timeOffset,   setTimeOffset]   = useState(0);            // hours, 0 = live
  const [coldStart,    setColdStart]    = useState(false);

  // ── WS messages buffer (fed to LeftColumn) ────────────────────────────
  const [wsMessages,   setWsMessages]   = useState([]);

  // ── Footer data sources ───────────────────────────────────────────────
  const [dataSources,  setDataSources]  = useState({});

  // ── LORO frozen date ──────────────────────────────────────────────────
  const [loroFrozen,   setLoroFrozen]   = useState(null);

  // ── Scenario / pin state ──────────────────────────────────────────────
  const [isPinMode,    setIsPinMode]    = useState(false);
  const [pinData,      setPinData]      = useState(null);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [events,        setEvents]        = useState([]);
  const [mapEngine,     setMapEngine]     = useState('deck');
  const [manualScenarioOpen, setManualOpen] = useState(false);
  const [scenarioPointRequest, setScenReq] = useState(null);

  // ── Gate data ─────────────────────────────────────────────────────────
  const [pendingGates, setPendingGates] = useState([]);

  const wsRef         = useRef(null);
  const mapPollRef    = useRef(null);
  const detailPollRef = useRef(null);
  // The WebSocket snapshot always describes the default region; keep the selected region in a ref so a
  // snapshot for a DIFFERENT region never overwrites what the user is looking at.
  const selectedRegionRef = useRef(null);

  // ── WebSocket: direct connection, exponential back-off (§14.6) ───────
  useEffect(() => {
    let ws;
    let reconnectTimer;
    let retryDelay = 5_000;
    const MAX_DELAY = 60_000;

    function connect() {
      try {
        ws = createAlertWebSocket();
        wsRef.current = ws;
        ws.onopen = () => { retryDelay = 5_000; };

        ws.onmessage = (evt) => {
          try {
            const msg = JSON.parse(evt.data);
            // Feed all messages to LeftColumn
            setWsMessages(prev => [msg, ...prev].slice(0, 200));

            if (msg.type === 'snapshot') {
              // Full state snapshot on reconnect (§14.6)
              if (Array.isArray(msg.hexes) &&
                  (!msg.hexes.length || !selectedRegionRef.current ||
                   msg.hexes[0].region_code === selectedRegionRef.current)) setHexes(msg.hexes);
              if (msg.cold_start !== undefined) setColdStart(msg.cold_start);
              return;
            }
            if (msg.type === 'tier_change') {
              setHexes(prev => prev.map(h =>
                h.hex_id === msg.hex_id
                  ? { ...h, tier: msg.tier, risk_score: msg.risk_score }
                  : h
              ));
              if (msg.hex_id === selectedHexId)
                setPersistState({ declared: msg.persistent || false, cycles: 0 });
            } else if (msg.type === 'persist_declared') {
              if (msg.hex_id === selectedHexId)
                setPersistState({ declared: true, cycles: msg.cycles });
            } else if (msg.type === 'gate_pending') {
              setPendingGates(prev => [...prev.filter(g => g.hex_id !== msg.hex_id), msg]);
            } else if (msg.type === 'gate_approved') {
              setPendingGates(prev => prev.filter(g => g.hex_id !== msg.hex_id));
            }
          } catch (_) {}
        };
        ws.onerror = () => {};
        ws.onclose = () => {
          reconnectTimer = setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, MAX_DELAY);
        };
      } catch (_) {}
    }
    connect();
    return () => { clearTimeout(reconnectTimer); if (ws) ws.close(); };
  }, [selectedHexId]);

  useEffect(() => { selectedRegionRef.current = selectedRegionCode; }, [selectedRegionCode]);

  // ── Map fetch & poll (loads current region hexes and auto-selects top-risk hex) ───
  const fetchMap = useCallback(async (regCode = selectedRegionCode) => {
    try {
      const data = await getRiskMap(null, regCode);
      if (Array.isArray(data) && data.length === 0) {
        // A region with no scored hexes shows NO hexes (never the previously selected region's).
        setHexes([]);
        setSelectedHexId(null);
        return;
      }
      if (Array.isArray(data) && data.length > 0) {
        setHexes(data);
        // Auto-select primary high-risk hex so entire explainability stack lights up immediately (§13.4)
        setSelectedHexId(prev => {
          if (prev && data.some(h => h.hex_id === prev)) return prev;
          const top = data.find(h => h.tier === 'Red' || h.tier === 'Orange' || h.tier === 'Yellow') || data[0];
          return top.hex_id;
        });
        if (data[0]?.data_source) {
          setDataSources(typeof data[0].data_source === 'object' ? data[0].data_source : { rainfall: data[0].data_source });
          setDataSource(typeof data[0].data_source === 'object' ? (data[0].data_source?.rainfall || 'live') : data[0].data_source);
        }
      }
    } catch (_) {}
  }, [selectedRegionCode]);

  useEffect(() => {
    fetchMap(selectedRegionCode);
    mapPollRef.current = setInterval(() => fetchMap(selectedRegionCode), POLL_MS);
    return () => clearInterval(mapPollRef.current);
  }, [selectedRegionCode, fetchMap]);

  // ── Region change handler ─────────────────────────────────────────────
  const handleRegionChange = async (regCode) => {
    setSelectedRegionCode(regCode);
    setSelectedHexId(null);
    await fetchMap(regCode);
  };

  // ── Any-Hilly-Location Onboarding handler (§6, §14.2) ──────────────────
  const handleResolveQuery = async (query) => {
    setIsResolving(true);
    try {
      const res = await resolveRegion(query);
      if (res?.success && res?.region_code) {
        setSelectedRegionCode(res.region_code);
        setSelectedHexId(null);
        await fetchMap(res.region_code);
        setWsMessages(prev => [{
          type: 'region_onboarded',
          region: res.label || res.region_code,
          hex_count: res.hex_count,
          timestamp: new Date().toISOString(),
        }, ...prev]);
      }
    } catch (err) {
      console.warn('Failed to resolve region:', err);
    } finally {
      setIsResolving(false);
    }
  };

  // ── Deliberate IoT sensor failure demonstration (§14.5) ────────────────
  const handleToggleIoT = async () => {
    try {
      const res = await toggleIoTSensor();
      const offline = res?.status === 'offline';
      setIotOffline(offline);
      setDataSources(prev => ({
        ...prev,
        rainfall: offline ? 'satellite_fallback' : 'live_iot',
      }));
      setWsMessages(prev => [{
        type: 'sensor_status_changed',
        sensor_id: res?.sensor_id || 'IOT_WAYANAD_001',
        status: res?.status || (offline ? 'offline' : 'healthy'),
        timestamp: new Date().toISOString(),
      }, ...prev]);
    } catch (err) {
      console.warn('Failed to toggle IoT:', err);
    }
  };

  // ── LORO frozen date ──────────────────────────────────────────────────
  useEffect(() => {
    getLoroResults().then(r => {
      setLoroFrozen(r?.summary?.frozen_at || r?.frozen_at || 'Stage 4');
    }).catch(() => {});
  }, []);

  // ── Historical events for map pins (510 real multiregion events) ──────
  useEffect(() => {
    getEventsMap().then(data => {
      if (Array.isArray(data)) setEvents(data);
    }).catch(() => {});
  }, []);

  // ── Detail poll on hex select ─────────────────────────────────────────
  useEffect(() => {
    clearInterval(detailPollRef.current);
    if (!selectedHexId) { setRisk(null); setHistory([]); setInundation(null); return; }

    const fetchDetail = async () => {
      try {
        const r = await getRisk(selectedHexId);
        setRisk(r);
        if (r?.data_source) setDataSources(r.data_source);
      } catch (_) {}
      try {
        const h = await getRiskHistory(selectedHexId);
        setHistory(Array.isArray(h) ? h : []);
      } catch (_) {}
      if (risk?.tier === 'Orange' || risk?.tier === 'Red') {
        try {
          const inv = await getInundation(selectedHexId);
          setInundation(inv);
        } catch (_) {}
      }
    };
    fetchDetail();
    detailPollRef.current = setInterval(fetchDetail, POLL_MS);
    return () => clearInterval(detailPollRef.current);
  }, [selectedHexId]);

  // ── Current region (first onboarded region from hexes) ───────────────
  const currentRegion = hexes.length > 0
    ? { region_code: hexes[0].region_code, region_label: hexes[0].region_label,
        state: hexes[0].state, district: hexes[0].district }
    : null;

  const selectedHex = hexes.find(h => h.hex_id === selectedHexId) || null;

  // ── Response Unit view ────────────────────────────────────────────────
  if (role === 'Response Unit') {
    return (
      <div className="app-shell">
        <AppHeader
          pendingGates={pendingGates.length}
          coldStart={coldStart}
          region={currentRegion}
          selectedRegionCode={selectedRegionCode}
          onRegionChange={handleRegionChange}
          onResolveQuery={handleResolveQuery}
          isResolving={isResolving}
          iotOffline={iotOffline}
          onToggleIoT={handleToggleIoT}
          onRoleChange={setRole}
        />
        <div className="app-body ru-mode">
          <ResponseUnitView hexes={hexes} alerts={pendingGates} region={currentRegion} />
        </div>
        <AppFooter dataSources={dataSources} frozenDate={loroFrozen} />
      </div>
    );
  }

  // ── Decision Authority console (default) ──────────────────────────────
  return (
    <div className="app-shell">

      {/* ── Header (§13.4) ── */}
      <AppHeader
        pendingGates={pendingGates.length}
        coldStart={coldStart}
        region={currentRegion}
        selectedRegionCode={selectedRegionCode}
        onRegionChange={handleRegionChange}
        onResolveQuery={handleResolveQuery}
        isResolving={isResolving}
        iotOffline={iotOffline}
        onToggleIoT={handleToggleIoT}
        onRoleChange={setRole}
      />

      {/* ── Body: Left | Center | Right ── */}
      <div className="app-body">

        {/* Left column — institutional record (§13.4) */}
        <LeftColumn wsAlerts={wsMessages} pendingGates={pendingGates} />

        {/* Center — map zone */}
        <div className="center-map-zone">
          {/* Map controls bar */}
          <div className="map-controls-bar">
            <HazardToggle mode={hazardMode} onChange={setHazardMode} />
            <TimeScrubber
              offsetHours={timeOffset}
              onChange={setTimeOffset}
            />
            {/* Map Engine Toggle */}
            <button
              className="cir-btn cir-btn--ghost"
              style={{ padding: '6px 12px', fontSize: 11 }}
              onClick={() => setMapEngine(e => e === 'deck' ? 'leaflet' : 'deck')}
              title="Toggle Map Engine (3D deck.gl H3 / 2D Leaflet)"
            >
              {mapEngine === 'deck' ? '⬡ 3D deck.gl' : '🗺️ 2D Leaflet'}
            </button>
            <SensorLabel />
          </div>

          {hexes.length === 0 && (
            <div style={{ padding: '8px 14px', background: 'var(--warning-soft)', color: 'var(--warning)', fontSize: 12, lineHeight: 1.4, borderBottom: '1px solid rgba(245,158,11,0.25)' }}>
              No scored hexes for this region yet. Scores appear after the scoring cycle has run for it
              (set HYDRASENSE_SCORE_REGIONS on the backend). Nothing is estimated in the meantime.
            </div>
          )}

          {/* Map display */}
          <div className="map-container">
            {mapEngine === 'deck' ? (
              <DeckHexMap
                hexes={hexes}
                selectedHexId={selectedHexId}
                onSelectHex={setSelectedHexId}
                onPinDrop={setPinData}
                pinData={pinData}
                onEventSelect={setSelectedEvent}
                events={events}
                hazardMode={hazardMode}
              />
            ) : (
              <HexMap
                hexes={hexes}
                selectedHexId={selectedHexId}
                onSelectHex={setSelectedHexId}
                onPinDrop={setPinData}
                pinData={pinData}
                onEventSelect={setSelectedEvent}
                events={events}
                hazardMode={hazardMode}
              />
            )}
          </div>
        </div>

        {/* Right column — explainability stack (§13.4) */}
        <div className="right-stack">
          {/* Persistent Threat Badge */}
          {selectedHexId && (
            <PersistentThreatBadge
              declared={persistState.declared}
              cycles={persistState.cycles}
              tier={risk?.tier}
            />
          )}

          {/* Three threat products (§13.1) */}
          {risk && (
            <ConfidenceLeadTime risk={risk} />
          )}

          {/* FS uncertainty band with widened tag (§13.4) */}
          {risk && (
            <div className="panel" style={{ margin: '0 12px 8px', padding: '10px 12px' }}>
              <div className="panel-title">Factor of Safety</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span className="metric-value fs-value">
                  {risk.factor_of_safety?.toFixed(2) ?? '—'}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  [{risk.factor_of_safety_min?.toFixed(2) ?? '—'} –
                   {risk.factor_of_safety_max?.toFixed(2) ?? '—'}]
                </span>
                {risk.fs_band_widened_for_no_calibration && (
                  <span className="stale-badge" style={{ marginLeft: 4 }}>
                    widened
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Feature contributions */}
          {risk && <FeaturePanel features={risk.top_contributing_features} />}

          {/* Trend sparkline */}
          {history.length > 0 && <TrendLine history={history} />}

          {/* Inundation (gated Orange/Red) */}
          {inundation && <InundationView tier={risk?.tier} inundation={inundation} />}

          {/* Two-person gate */}
          {selectedHexId && <GatePanel hexId={selectedHexId} onApprove={() => {}} />}

          {/* Incident Action Plan (IAP) with dashed live document border (§13.4) */}
          <IncidentActionPlan selectedHex={selectedHex} region={currentRegion} />

          {/* LORO validation + data-source health panel (§13.4 / §16.8) */}
          <ValidationPanel />
          <LoroPanel />

          {/* Historical event */}
          {selectedEvent && <HistoricalEventPanel event={selectedEvent} />}

          {/* Alert feed */}
          <AlertFeed />

          {/* Citizen preview panel (§13.7) */}
          <CitizenPreviewPanel selectedHex={selectedHex} region={currentRegion} />

          {/* Data source label */}
          <div style={{ padding: '8px 12px' }}>
            <DataSourceLabel source={dataSource} />
          </div>

          {/* Manual scenario */}
          <ManualScenarioPanel
            open={manualScenarioOpen}
            onClose={() => setManualOpen(false)}
            pointRequest={scenarioPointRequest}
          />
        </div>
      </div>

      {/* ── Footer — agency dots (§13.4) ── */}
      <AppFooter dataSources={dataSources} frozenDate={loroFrozen} />
    </div>
  );
}
