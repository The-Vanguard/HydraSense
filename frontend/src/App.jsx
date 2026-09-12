/**
 * App.jsx — HydraSense Main Dashboard
 * Top-level layout: always-visible DataSourceLabel banner, sidebar panels, interactive Leaflet map.
 * Polling: GET /risk/map every 10s; GET /risk/{hex_id} + /history + /inundation on hex selection.
 * Interactive Geospatial Analysis: Dropping or dragging pins enables regional hazard evaluation
 * based on terrain slope, surface classification, and meteorological conditions.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getRiskMap, getRisk, getRiskHistory, getInundation, getUncertainty } from './api/client';
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
import ManualScenarioPanel  from './components/ManualScenarioPanel';

const POLL_MS         = 10_000;
const POLL_MS_INITIAL =  3_000;  // faster first-fetch

export default function App() {
  const [hexes,         setHexes]         = useState([]);
  const [selectedHexId, setSelectedHexId] = useState(null);
  const [risk,          setRisk]          = useState(null);
  const [history,       setHistory]       = useState([]);
  const [inundation,    setInundation]    = useState(null);
  const [validation,    setValidation]    = useState(null);
  const [dataSource,    setDataSource]    = useState('live');
  const [demoStage,     setDemoStage]     = useState(null);

  // Nothing selected on load -- just the map, no sidebar panel pre-populated.
  const [isPinMode,     setIsPinMode]     = useState(false);
  const [pinData,       setPinData]       = useState(null);
  const [manualScenarioOpen, setManualScenarioOpen] = useState(false);   // manual what-if simulator
  const [scenarioPointRequest, setScenarioPointRequest] = useState(null);   // {hexId, ts} -- pin clicked while scenario open

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
        setDemoStage(r.demo_stage || null);
        setDataSource(r.data_source || 'live');
        setValidation(generateValidationForHex(r.tier));

        // Real Phase 5 factor-of-safety (+ band) for this hex, from real
        // observations -- merged onto the risk object so ConfidenceLeadTime
        // renders the same FS gauge shape it uses for pin-drop/manual
        // scenario, but with real values (or an honest note when this hex
        // has no real terrain data recorded yet, see task_3c7bb605).
        getUncertainty(selectedHexId)
          .then((unc) => setRisk({
            ...r,
            factor_of_safety: unc.factor_of_safety,
            factor_of_safety_min: unc.factor_of_safety_min,
            factor_of_safety_max: unc.factor_of_safety_max,
            factor_of_safety_note: unc.band_note,
          }))
          .catch(() => setRisk(r));

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



  // Selecting a Wayanad hex polygon restores live backend mode -- unless
  // Manual Scenario is open, in which case the click means "load this real
  // point's static data into the form" instead of switching views.
  const handleSelectHex = useCallback((hexId) => {
    if (manualScenarioOpen) {
      setScenarioPointRequest({ hexId, ts: Date.now() });
      return;
    }
    setIsPinMode(false);
    setPinData(null);
    setSelectedHexId(hexId);
    setRisk(null);
    setHistory([]);
    setInundation(null);
    setValidation(generateValidationForHex('Yellow'));
    setDataSource('live');
    setDemoStage(null);
  }, [manualScenarioOpen]);

  // Dropping or moving a custom pin engages regional analysis
  const handlePinDrop = useCallback((data) => {
    setManualScenarioOpen(false);
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

  const handleOpenManualScenario = useCallback(() => {
    setManualScenarioOpen(true);
  }, []);
  const handleCloseManualScenario = useCallback(() => setManualScenarioOpen(false), []);

  const iotOffline = risk?.iot_anomaly_flag ?? false;
  const currentTier = risk?.tier ?? 'Green';

  // Nothing picked yet on a fresh load/refresh -- no sidebar at all, just the map.
  const hasSelection = Boolean(manualScenarioOpen || selectedHexId || (isPinMode && pinData));

  return (
    <div className="app-shell">
      {/* ── Always-visible banner (SRS §13) ── */}
      <DataSourceLabel dataSource={dataSource} stage={demoStage} />

      <div className={`app-body${hasSelection ? '' : ' no-sidebar'}`}>
        {/* ── Sidebar panels (only once a hex/pin/event is selected) ── */}
        {hasSelection && (
        <aside className="sidebar">

          {manualScenarioOpen ? (
            <ManualScenarioPanel onClose={handleCloseManualScenario} externalPointRequest={scenarioPointRequest} />
          ) : (
          <>
          {/* Location selector panel: Custom Pin vs Hex */}
          {isPinMode && pinData ? (
            <div className="panel pin-control-panel">
              <div className="panel-title">
                <span>Analyzed Location</span>
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
          </>
          )}

        </aside>
        )}

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

          {/* Manual what-if scenario toggle -- real model, hypothetical input */}
          <button
            onClick={handleOpenManualScenario}
            style={{
              position: 'absolute', top: 10, right: 10, zIndex: 500,
              background: 'rgba(13,17,23,0.9)', color: '#a78bfa',
              border: '1px solid #a78bfa', borderRadius: 6,
              fontSize: 12, fontWeight: 600, padding: '6px 12px', cursor: 'pointer',
            }}
          >
            Manual Scenario
          </button>
        </main>
      </div>
    </div>
  );
}
