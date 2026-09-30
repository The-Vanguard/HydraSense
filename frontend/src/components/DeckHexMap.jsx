/**
 * DeckHexMap.jsx — deck.gl H3HexagonLayer + MapLibre GL JS
 * Final.md §15.4 Swap #2: replaces Leaflet-based HexMap.
 * Includes graceful fallback to Leaflet HexMap if WebGL is unavailable or fails.
 *
 * Features (all per Final.md §13.4):
 *  - H3HexagonLayer with per-hex tier color + confidence desaturation
 *  - Hover tooltip: "no local calibration" / "widened geotechnical uncertainty"
 *  - Three-way hazard toggle: Compound / Flood / Landslide
 *  - Alert-resilience dot (instrumented_hex indicator)
 *  - Draggable pin analysis (preserved from original HexMap)
 *  - Real historical event pins across India
 *  - Auto-fit to active hexes (Wayanad pilot cluster)
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import Map, { NavigationControl } from 'react-map-gl/maplibre';
import maplibregl from 'maplibre-gl';
import DeckGL from '@deck.gl/react';
import { H3HexagonLayer } from '@deck.gl/geo-layers';
import { ScatterplotLayer } from '@deck.gl/layers';
import { LinearInterpolator, WebMercatorViewport } from '@deck.gl/core';
import { cellToLatLng } from 'h3-js';
import 'maplibre-gl/dist/maplibre-gl.css';

import HexMap from './HexMap';
import ErrorBoundary from './ErrorBoundary';

// Token-free Carto Dark Matter basemap style (matches dark command center theme)
const BASEMAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
const BASEMAP_LIGHT = 'https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json';
const INDIA_VIEW = { longitude: 82.8, latitude: 23.2, zoom: 4.3, pitch: 0, bearing: 0 };

// Default view — Wayanad pilot hex cluster (lat 11.51, lng 76.05)
const INITIAL_VIEW = {
  longitude: 76.047,
  latitude: 11.51,
  zoom: 13.0,
  pitch: 25,
  bearing: 0,
};

// Tier colours (match index.css --tier-*)
const TIER_RGBA = {
  Green:  [34,  197, 94,  210],
  Yellow: [234, 179, 8,   210],
  Orange: [249, 115, 22,  210],
  Red:    [239, 68,  68,  220],
};

function checkWebGL() {
  if (typeof window === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch (_) {
    return false;
  }
}

// Desaturate a tier colour for low-confidence hexes (§13.4)
function desaturate([r, g, b, a], factor) {
  const grey = 0.299 * r + 0.587 * g + 0.114 * b;
  return [
    Math.round(grey + (r - grey) * factor),
    Math.round(grey + (g - grey) * factor),
    Math.round(grey + (b - grey) * factor),
    a,
  ];
}

// Which tier to display based on hazard mode
function hexTier(hex, mode) {
  if (mode === 'flood')     return hex.flood_tier    || hex.tier || 'Green';
  if (mode === 'landslide') return hex.landslide_tier || hex.tier || 'Green';
  // Compound: higher of the two (§13.4)
  const ft = hex.flood_tier    || hex.tier || 'Green';
  const lt = hex.landslide_tier || hex.tier || 'Green';
  const rank = { Green: 0, Yellow: 1, Orange: 2, Red: 3 };
  return rank[ft] >= rank[lt] ? ft : lt;
}

// Confidence reason for tooltip (§13.4)
function confidenceReason(hex) {
  if (!hex.has_local_calibration && hex.fs_band_widened_for_no_calibration)
    return 'No local calibration + widened geotechnical uncertainty';
  if (!hex.has_local_calibration) return 'No local historical calibration';
  if (hex.fs_band_widened_for_no_calibration) return 'Widened geotechnical uncertainty';
  return null;
}

function DeckHexMapInner({
  hexes = [],
  selectedHexId,
  onSelectHex,
  onPinDrop,
  pinData,
  onEventSelect,
  events = [],
  hazardMode = 'compound',
  regionMarkers = [],          // [{region_code, label, lat, lon, worst_tier}] -- national view
  onRegionClick,
  nationalView = false,
  light = false,
}) {
  const [viewState, setViewState] = useState(nationalView ? INDIA_VIEW : INITIAL_VIEW);

  // National view: fit all region markers into the actual map size whenever it is switched on.
  const wrapRef = useRef(null);
  const markerKey = regionMarkers.map(m => m.region_code).join(',');
  useEffect(() => {
    if (!nationalView) return;
    let target = INDIA_VIEW;
    const el = wrapRef.current;
    if (regionMarkers.length > 1 && el && el.clientWidth > 50 && el.clientHeight > 50) {
      const lats = regionMarkers.map(m => m.lat), lons = regionMarkers.map(m => m.lon);
      try {
        const vp = new WebMercatorViewport({ width: el.clientWidth, height: el.clientHeight });
        const f = vp.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
                               { padding: Math.min(60, el.clientWidth / 8) });
        target = { longitude: f.longitude, latitude: f.latitude, zoom: Math.min(6, f.zoom), pitch: 0, bearing: 0 };
      } catch { /* keep INDIA_VIEW */ }
    }
    setViewState(prev => ({ ...prev, ...target, transitionDuration: 900,
      transitionInterpolator: new LinearInterpolator(['latitude', 'longitude', 'zoom']) }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nationalView, markerKey]);
  const [hoverInfo, setHoverInfo] = useState(null);
  const deckRef = useRef(null);

  // Auto-center camera when the SET of hexes changes (new region / first load) -- not on every poll, which
  // would throw away the user's pan and zoom every 10 seconds.
  const fitKeyRef = useRef(null);
  useEffect(() => {
    if (!hexes || hexes.length === 0) { fitKeyRef.current = null; return; }
    const fitKey = `${hexes[0]?.region_code}|${hexes[0]?.hex_id}|${hexes.length}`;
    if (fitKeyRef.current === fitKey) return;
    fitKeyRef.current = fitKey;
    try {
      let sumLat = 0, sumLng = 0, count = 0;
      let minLat = 90, maxLat = -90, minLng = 180, maxLng = -180;
      hexes.forEach(h => {
        if (h.hex_id) {
          const [lat, lng] = cellToLatLng(h.hex_id);
          sumLat += lat;
          sumLng += lng;
          count++;
          minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
          minLng = Math.min(minLng, lng); maxLng = Math.max(maxLng, lng);
        }
      });
      if (count > 0) {
        // Fit the camera to the hexes' extent: visible width at zoom z is ~1125 / 2^z degrees for an ~800 px
        // viewport, so z = log2(865 / span) leaves ~30% margin.  Clamped so a single hex is not over-zoomed
        // and a whole region is not lost (the old fixed 13.5 showed black for district-wide hex sets).
        const latSpan = maxLat - minLat;
        const lngSpan = (maxLng - minLng) * Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
        const span = Math.max(latSpan, lngSpan, 0.005);
        const fitZoom = Math.min(13.5, Math.max(6, Math.log2(865 / span)));
        setViewState(prev => ({
          ...prev,
          latitude: sumLat / count,
          longitude: sumLng / count,
          zoom: fitZoom,
          // K27 — flyTo animation when new hexes load (Final.md §13.4)
          transitionDuration: 1200,
          transitionInterpolator: new LinearInterpolator(['latitude', 'longitude', 'zoom']),
        }));
      }
    } catch (e) {
      console.warn('[DeckHexMap] Could not auto-center:', e);
    }
  }, [hexes]);

  // ── Build H3 layer ──────────────────────────────────────────────────────
  const hexLayer = new H3HexagonLayer({
    id: 'h3-risk-layer',
    data: hexes,
    pickable: true,
    wireframe: false,
    filled: true,
    extruded: false,
    getHexagon: d => d.hex_id,
    getFillColor: d => {
      const tier = hexTier(d, hazardMode);
      const base = TIER_RGBA[tier] || TIER_RGBA.Green;
      // Desaturate low-confidence hexes (§13.4)
      const conf = d.confidence_score ?? 100;
      const factor = conf < 40 ? 0.35 : conf < 65 ? 0.6 : conf < 80 ? 0.8 : 1.0;
      const color = factor < 1.0 ? desaturate(base, factor) : base;
      // Highlight selected
      if (d.hex_id === selectedHexId) return [255, 255, 255, 120];
      return color;
    },
    getLineColor: d => d.hex_id === selectedHexId ? [255, 255, 255, 255] : [40, 40, 40, 180],
    lineWidthMinPixels: 1.5,
    onClick: ({ object }) => { if (object) onSelectHex?.(object.hex_id); },
    onHover: info => setHoverInfo(info.object ? info : null),
    updateTriggers: {
      getFillColor: [hexes, selectedHexId, hazardMode],
      getLineColor: [selectedHexId],
    },
    // K27 — smooth color transitions when tier/hazard mode changes (Final.md §13.4)
    transitions: {
      getFillColor: { duration: 300, type: 'interpolation' },
      getLineColor: { duration: 150, type: 'interpolation' },
    },
  });

  // ── Alert-resilience dot layer (§13.4) — hollow = Layer-3 only ─────────
  const dotLayer = new ScatterplotLayer({
    id: 'resilience-dot-layer',
    data: hexes.filter(h => h.instrumented_hex !== undefined),
    pickable: false,
    getPosition: d => [d.lng ?? d.lon ?? 76.047, d.lat ?? 11.51, 0],
    getRadius: 300,
    getFillColor: d => d.instrumented_hex
      ? [96, 165, 250, 200]   // filled = has Layer 0/1 coverage
      : [96, 165, 250, 0],    // hollow drawn via stroke only
    getLineColor: [96, 165, 250, 180],
    stroked: true,
    lineWidthMinPixels: 1,
  });

  // ── Event pin layer (historical events across India) ────────────────────
  const eventLayer = new ScatterplotLayer({
    id: 'event-pins',
    data: events,
    pickable: true,
    getPosition: d => [d.lon ?? d.lng ?? 80, d.lat ?? 20, 0],
    getRadius: 1800,
    radiusMinPixels: 4,
    radiusMaxPixels: 15,
    getFillColor: [56, 189, 248, 210],
    getLineColor: [255, 255, 255, 200],
    stroked: true,
    lineWidthMinPixels: 1.5,
    onClick: ({ object }) => { if (object) onEventSelect?.(object); },
  });

  // ── Region markers (national view): one circle per region, coloured by its worst current tier ──
  const regionLayer = new ScatterplotLayer({
    id: 'region-markers',
    data: regionMarkers,
    pickable: true,
    getPosition: d => [d.lon, d.lat, 0],
    getRadius: 22000,
    radiusMinPixels: 9,
    radiusMaxPixels: 26,
    getFillColor: d => (TIER_RGBA[d.worst_tier] ? [...TIER_RGBA[d.worst_tier].slice(0, 3), 200] : [120, 120, 120, 160]),
    getLineColor: [255, 255, 255, 230],
    stroked: true,
    lineWidthMinPixels: 2,
    onClick: ({ object }) => { if (object) onRegionClick?.(object.region_code); },
    onHover: info => setHoverInfo(info.object ? info : null),
    updateTriggers: { getFillColor: [regionMarkers] },
  });

  const layers = [hexLayer, dotLayer, eventLayer, regionLayer];

  return (
    <div ref={wrapRef} style={{ position: 'relative', width: '100%', height: '100%' }}>
      <DeckGL
        ref={deckRef}
        viewState={viewState}
        controller={true}
        layers={layers}
        onViewStateChange={({ viewState: vs }) => setViewState(vs)}
        style={{ position: 'absolute', inset: 0 }}
      >
        <Map
          mapLib={maplibregl}
          mapStyle={light ? BASEMAP_LIGHT : BASEMAP_STYLE}
          reuseMaps
          attributionControl={false}
        >
          <NavigationControl position="bottom-right" />
        </Map>
      </DeckGL>

      {/* Hover tooltip — confidence reason (§13.4) */}
      {hoverInfo?.object && (
        <div style={{
          position: 'absolute',
          left: hoverInfo.x + 12,
          top: hoverInfo.y - 8,
          background: 'rgba(13,17,23,0.95)',
          border: '1px solid #30363d',
          borderRadius: 6,
          padding: '8px 12px',
          fontSize: 11,
          color: '#e6edf3',
          pointerEvents: 'none',
          zIndex: 1000,
          maxWidth: 240,
          boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
        }}>
          {hoverInfo.object.region_code && !hoverInfo.object.hex_id ? (
            <div style={{ fontWeight: 700 }}>
              {hoverInfo.object.label || hoverInfo.object.region_code}
              <div style={{ fontWeight: 400, color: '#8b949e' }}>
                worst current tier: {hoverInfo.object.worst_tier || 'no scores'} · click to open
              </div>
            </div>
          ) : (<>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            {hexTier(hoverInfo.object, hazardMode)}
            {hoverInfo.object.confidence_score != null && (
              <span style={{ fontWeight: 400, color: '#8b949e', marginLeft: 8 }}>
                Conf {Math.round(hoverInfo.object.confidence_score)}
              </span>
            )}
          </div>
          {hoverInfo.object.village && (
            <div style={{ color: '#e6edf3', marginBottom: 2 }}>
              {hoverInfo.object.village_is_nearest ? 'near ' : ''}{hoverInfo.object.village}
            </div>
          )}
          {hoverInfo.object.hex_id && (
            <div style={{ color: '#6e7681', fontSize: 9, fontFamily: 'monospace', marginBottom: 4 }}>
              cell {hoverInfo.object.hex_id}
            </div>
          )}
          {/* Confidence reason (§13.4) */}
          {(() => {
            const reason = confidenceReason(hoverInfo.object);
            return reason ? (
              <div style={{
                color: '#eab308', fontSize: 10, fontStyle: 'italic',
                borderTop: '1px solid #21262d', paddingTop: 4, marginTop: 4,
              }}>
                ⚠ {reason}
              </div>
            ) : null;
          })()}
          {/* Hazard tier split if compound and tiers differ */}
          {hazardMode === 'compound' &&
           hoverInfo.object.flood_tier &&
           hoverInfo.object.landslide_tier &&
           hoverInfo.object.flood_tier !== hoverInfo.object.landslide_tier && (
            <div style={{ fontSize: 9, color: '#8b949e', marginTop: 4 }}>
              Flood: {hoverInfo.object.flood_tier} ·
              Landslide: {hoverInfo.object.landslide_tier}
            </div>
          )}
          </>)}
        </div>
      )}
    </div>
  );
}

/**
 * DeckHexMap with automatic WebGL detection and ErrorBoundary fallback to HexMap (Leaflet).
 */
export default function DeckHexMap(props) {
  const [hasWebGL] = useState(checkWebGL);

  if (!hasWebGL) {
    return <HexMap {...props} />;
  }

  return (
    <ErrorBoundary fallback={<HexMap {...props} />}>
      <DeckHexMapInner {...props} />
    </ErrorBoundary>
  );
}
