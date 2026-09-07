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

const POLL_MS         = 10_000;
const POLL_MS_INITIAL =  3_000;  // faster first-fetch

// ── Default location shown immediately on load (Wayanad, Kerala) ─────────────
const DEFAULT_LOCATION = {
  risk: {
    tier:              'Yellow',
    risk_score:        47,
    confidence_score:  84,
    lead_time_min:     null,
    lead_time_basis:   'no_red_crossing_in_forecast_window',
    factor_of_safety:  1.31,
    factor_of_safety_min: null,
    factor_of_safety_max: null,
    coordinates:       { lat: 11.607, lng: 76.082 },
  },
  surface: { label: 'Wayanad, Kerala' },
  features: [
    { feature: 'rainfall_24h',                   contribution: 0.22 },
    { feature: 'soil_saturation_ratio',          contribution: 0.19 },
    { feature: 'slope_deg',                      contribution: 0.15 },
    { feature: 'antecedent_precipitation_index', contribution: 0.12 },
    { feature: 'factor_of_safety',               contribution: 0.09 },
    { feature: 'TWI',                            contribution: 0.06 },
  ],
  history:    [],
  inundation: null,
  validation: null,
  alert:      null,
};

export default function App() {
  const [hexes,         setHexes]         = useState([]);
  const [selectedHexId, setSelectedHexId] = useState(null);
  const [risk,          setRisk]          = useState(DEFAULT_LOCATION.risk);
  const [history,       setHistory]       = useState([]);
  const [inundation,    setInundation]    = useState(null);
  const [validation,    setValidation]    = useState(null);
  const [dataSource,    setDataSource]    = useState('live');
  const [demoStage,     setDemoStage]     = useState(null);

  const [isPinMode,     setIsPinMode]     = useState(true);   // start in pin mode with default
  const [pinData,       setPinData]       = useState(DEFAULT_LOCATION);

  const mapPollRef    = useRef(null);
  const detailPollRef = useRef(null);

  // ── Map polling — fast initial, then normal cadence ──────────────────────
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
    // First fetch immediately, second after 3s, then settle to 10s cadence
    fetchMap();
    const fastTimer = setTimeout(() => {
      fetchMap();
      mapPollRef.current = setInterval(fetchMap, POLL_MS);
    }, POLL_MS_INITIAL);
    return () => {
      clearTimeout(fastTimer);
      clearInterval(mapPollRef.current);
    };
  }, [fetchMap]);

  // ── Detail polling for selected hex (paused during pin mode) ─────────────
  const fetchDetail = useCallback(() => {
    if (!selectedHexId || isPinMode) return;

    getRisk(selectedHexId)
      .then((r) => {
        setRisk(r);
        setDemoStage(r.demo_stage || null);
        setDataSource(r.data_source || 'live');
        setValidation(generateValidationForHex(r.tier));

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
              <div className="panel-title">
                <span>📍 Analyzed Location</span>
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
