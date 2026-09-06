/**
 * App.jsx — HydraSense Phase 12
 * Top-level layout: always-visible DataSourceLabel banner, sidebar panels, Leaflet map.
 * Polling: GET /risk/map every 10s; GET /risk/{hex_id} + /history + /inundation on selection.
 * SRS §15, §20.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { getRiskMap, getRisk, getRiskHistory, getInundation } from './api/client';

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
  // Map data
  const [hexes,         setHexes]         = useState([]);
  // Selected hex detail
  const [selectedHexId, setSelectedHexId] = useState(null);
  const [risk,          setRisk]          = useState(null);
  const [history,       setHistory]       = useState([]);
  const [inundation,    setInundation]    = useState(null);
  // Global data source + demo stage (from map response)
  const [dataSource,    setDataSource]    = useState('live');
  const [demoStage,     setDemoStage]     = useState(null);

  const mapPollRef    = useRef(null);
  const detailPollRef = useRef(null);

  // ── Map polling ──────────────────────────────────────────────────────────
  const fetchMap = useCallback(() => {
    getRiskMap()
      .then((data) => {
        setHexes(data);
        if (data.length > 0) {
          setDataSource(data[0].data_source || 'live');
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchMap();
    mapPollRef.current = setInterval(fetchMap, POLL_MS);
    return () => clearInterval(mapPollRef.current);
  }, [fetchMap]);

  // ── Detail polling for selected hex ─────────────────────────────────────
  const fetchDetail = useCallback(() => {
    if (!selectedHexId) return;

    getRisk(selectedHexId)
      .then((r) => {
        setRisk(r);
        setDemoStage(r.demo_stage || null);
        setDataSource(r.data_source || 'live');

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
  }, [selectedHexId]);

  useEffect(() => {
    clearInterval(detailPollRef.current);
    if (!selectedHexId) return;
    fetchDetail();
    detailPollRef.current = setInterval(fetchDetail, POLL_MS);
    return () => clearInterval(detailPollRef.current);
  }, [selectedHexId, fetchDetail]);

  // Auto-select first hex once map data arrives
  useEffect(() => {
    if (hexes.length > 0 && !selectedHexId) {
      setSelectedHexId(hexes[0].hex_id);
    }
  }, [hexes, selectedHexId]);

  const handleSelectHex = useCallback((hexId) => {
    setSelectedHexId(hexId);
    setRisk(null);
    setHistory([]);
    setInundation(null);
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

          {/* Hex selector info */}
          {selectedHexId && (
            <div className="panel" style={{ paddingBottom: 8 }}>
              <div className="panel-title">Selected Hex</div>
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
          )}

          {/* Risk score + confidence + lead time */}
          <ConfidenceLeadTime risk={risk} />

          {/* 1D trend */}
          <TrendLine history={history} />

          {/* Inundation — only renders at Orange/Red (code gate inside component) */}
          <InundationView tier={currentTier} inundation={inundation} />

          {/* Feature contributions */}
          <FeaturePanel features={risk?.top_contributing_features ?? []} />

          {/* Alert feed */}
          <AlertFeed />

          {/* LOEO validation — static, fetched once on mount */}
          <ValidationPanel />

        </aside>

        {/* ── Map ── */}
        <main className="map-container">
          <HexMap
            hexes={hexes}
            selectedHexId={selectedHexId}
            onSelectHex={handleSelectHex}
          />
          {/* Sensor offline label (SRS §16) */}
          <SensorLabel iotAnomalyFlag={iotOffline} />
        </main>
      </div>
    </div>
  );
}
