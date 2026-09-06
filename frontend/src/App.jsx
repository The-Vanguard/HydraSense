/**
 * App.jsx — HydraSense Main Dashboard
 * Top-level layout: always-visible DataSourceLabel banner, sidebar panels, interactive Leaflet map.
 * Polling: GET /risk/map every 10s; GET /risk/{hex_id} + /history + /inundation on hex selection.
 * Interactive Geospatial Analysis: Dropping or dragging pins enables regional hazard evaluation
 * based on terrain slope, surface classification, and meteorological conditions.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getRiskMap, getRisk, getRiskHistory, getInundation } from './api/client';
import { generateValidationForHex } from './utils/pinSimulation';

import DataSourceLabel     from './components/DataSourceLabel';
import SensorLabel         from './components/SensorLabel';
import HexMap              from './components/HexMap';
import ConfidenceLeadTime  from './components/ConfidenceLeadTime';
import TrendLine           from './components/TrendLine';
import InundationView      from './components/InundationView';
import FeaturePanel        from './components/FeaturePanel';
import ValidationPanel     from './components/ValidationPanel';
import AlertFeed           from './components/AlertFeed';

const POLL_MS = 10_000;

export default function App() {
  // Map hexes from backend
  const [hexes,         setHexes]         = useState([]);
  // Selected hex detail
  const [selectedHexId, setSelectedHexId] = useState(null);
  const [risk,          setRisk]          = useState(null);
  const [history,       setHistory]       = useState([]);
  const [inundation,    setInundation]    = useState(null);
  // Dynamic validation metrics
  const [validation,    setValidation]    = useState(null);
  // Global data source + demo stage
  const [dataSource,    setDataSource]    = useState('live');
  const [demoStage,     setDemoStage]     = useState(null);

  // Custom placed pin state
  const [isPinMode,     setIsPinMode]     = useState(false);
  const [pinData,       setPinData]       = useState(null);

  const mapPollRef    = useRef(null);
  const detailPollRef = useRef(null);

  // ── Map polling ──────────────────────────────────────────────────────────
  const fetchMap = useCallback(() => {
    getRiskMap()
      .then((data) => {
        setHexes(data);
        if (data.length > 0 && !isPinMode) {
          setDataSource(data[0].data_source || 'live');
        }
      })
      .catch(() => {});
  }, [isPinMode]);

  useEffect(() => {
    fetchMap();
    mapPollRef.current = setInterval(fetchMap, POLL_MS);
    return () => clearInterval(mapPollRef.current);
  }, [fetchMap]);

  // ── Detail polling for selected hex (paused during pin simulation) ────────
  const fetchDetail = useCallback(() => {
    if (!selectedHexId || isPinMode) return;

    getRisk(selectedHexId)
      .then((r) => {
        setRisk(r);
        setDemoStage(r.demo_stage || null);
        setDataSource(r.data_source || 'live');
        setValidation(generateValidationForHex(r.tier));

        // Fetch inundation only if tier >= Orange (SRS §15 code gate)
        if (['Orange', 'Red'].includes(r.tier)) {
          getInundation(selectedHexId)
            .then(setInundation)
            .catch(() => setInundation(null));
        } else {
          setInundation(null);
        }
      })
      .catch(() => {});

    getRiskHistory(selectedHexId)
      .then(setHistory)
      .catch(() => {});
  }, [selectedHexId, isPinMode]);

  useEffect(() => {
    clearInterval(detailPollRef.current);
    if (!selectedHexId || isPinMode) return;
    fetchDetail();
    detailPollRef.current = setInterval(fetchDetail, POLL_MS);
    return () => clearInterval(detailPollRef.current);
  }, [selectedHexId, isPinMode, fetchDetail]);

  // Auto-select first hex on initial load once map data arrives
  useEffect(() => {
    if (hexes.length > 0 && !selectedHexId && !isPinMode) {
      setSelectedHexId(hexes[0].hex_id);
    }
  }, [hexes, selectedHexId, isPinMode]);

  // Selecting a Wayanad hex polygon restores live backend mode
  const handleSelectHex = useCallback((hexId) => {
    setIsPinMode(false);
    setPinData(null);
    setSelectedHexId(hexId);
    setRisk(null);
    setHistory([]);
    setInundation(null);
    setValidation(generateValidationForHex('Yellow'));
    setDataSource('live');
    setDemoStage(null);
  }, []);

  // Dropping or moving a custom pin engages regional analysis
  const handlePinDrop = useCallback((data) => {
    setIsPinMode(true);
    setPinData(data);
    setSelectedHexId(data.risk.hex_id);
    setRisk(data.risk);
    setHistory(data.history);
    setInundation(data.inundation);
    setValidation(data.validation);
    setDataSource('live');
    setDemoStage(
      data.surface?.surface === 'coromandel_coast'
        ? 'Coromandel Coastal'
        : data.surface?.surface === 'flat_land'
        ? 'Plains Region'
        : 'Western Ghats Slope'
    );
  }, []);

  const iotOffline = risk?.iot_anomaly_flag ?? false;
  const currentTier = risk?.tier ?? 'Green';

  return (
    <div className="app-shell">
      {/* ── Always-visible banner (SRS §13) ── */}
      <DataSourceLabel dataSource={dataSource} stage={demoStage} />

      <div className="app-body">
        {/* ── Sidebar panels ── */}
        <aside className="sidebar">

          {/* Location selector panel: Custom Pin vs Hex */}
          {isPinMode && pinData ? (
            <div className="panel pin-control-panel">
              <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>📍 Analyzed Location</span>
                {hexes.length > 0 && (
                  <button
                    type="button"
                    className="pin-action-btn back-btn"
                    style={{ padding: '3px 10px', fontSize: 11 }}
                    onClick={() => handleSelectHex(hexes[0].hex_id)}
                  >
                    ↩ Wayanad Hex
                  </button>
                )}
              </div>

              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: '#e6edf3' }}>
                    {pinData.surface?.label || 'Placed Point'}
                  </div>
                  <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>
                    {pinData.risk.coordinates?.lat.toFixed(4)}° N, {pinData.risk.coordinates?.lng.toFixed(4)}° E
                  </div>
                </div>
                {risk?.tier && (
                  <span className={`tier-badge ${risk.tier}`}>
                    <span className="pulse-dot" />
                    {risk.tier}
                  </span>
                )}
              </div>
            </div>
          ) : selectedHexId ? (
            <div className="panel" style={{ paddingBottom: 8 }}>
              <div className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>Selected Hex</span>
                <span style={{ fontSize: 10, color: '#8b949e' }}>Click map to drop pin</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <code className="hex-id-text">{selectedHexId}</code>
                {risk?.tier && (
                  <span className={`tier-badge ${risk.tier}`}>
                    <span className="pulse-dot" />
                    {risk.tier}
                  </span>
                )}
              </div>
              {risk && (
                <div style={{ fontSize: 10, color: '#8b949e', marginTop: 4 }}>
                  {hexes.find(h => h.hex_id === selectedHexId)?.village ?? ''}
                </div>
              )}
            </div>
          ) : null}

          {/* Risk score + confidence + lead time */}
          <ConfidenceLeadTime risk={risk} />

          {/* 1D trend */}
          <TrendLine history={history} />

          {/* Inundation — only renders at Orange/Red (code gate inside component) */}
          <InundationView tier={currentTier} inundation={inundation} />

          {/* Feature contributions */}
          <FeaturePanel features={risk?.top_contributing_features ?? []} />

          {/* Alert feed (displays custom pin alert if Orange/Red) */}
          <AlertFeed customAlert={isPinMode ? pinData?.alert : null} />

          {/* LOEO validation — dynamic metrics */}
          <ValidationPanel validation={validation} />

        </aside>

        {/* ── Map ── */}
        <main className="map-container">
          <HexMap
            hexes={hexes}
            selectedHexId={isPinMode ? null : selectedHexId}
            onSelectHex={handleSelectHex}
            onPinDrop={handlePinDrop}
            pinData={pinData}
          />
          {/* Sensor offline label (SRS §16) */}
          <SensorLabel iotAnomalyFlag={iotOffline} />
        </main>
      </div>
    </div>
  );
}
