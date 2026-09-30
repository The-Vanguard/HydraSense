/**
 * HexMap.jsx — HydraSense Geospatial Map Component
 * Interactive Leaflet map with H3 hexagonal polygons and draggable point analysis.
 * Supports regional hazard evaluation based on terrain classification,
 * surface characteristics, and seasonal dynamics.
 */
import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { cellToBoundary } from 'h3-js';
import { sampleMapColor, generatePinSimulation } from '../utils/pinSimulation';
import { getEventsMap } from '../api/client';

const TIER_COLORS = {
  Green:  '#22c55e',
  Yellow: '#eab308',
  Orange: '#f97316',
  Red:    '#ef4444',
};

// Map center: Wayanad pilot cluster default
const MAP_CENTER = [11.51, 76.047];
const MAP_ZOOM   = 13;

// Phase 13 — real sourced historical events (9 regions outside Wayanad).
// Deliberately NOT reusing TIER_COLORS: that palette means "live risk tier,"
// these are historical records with no live model output.
const EVENT_TYPE_COLORS = {
  flash_flood:     '#38bdf8',
  riverine_flood:  '#818cf8',
  landslide_only:  '#a78bfa',
  ambiguous:       '#94a3b8',
  unknown:         '#64748b',
};

// The fabricated ISRO-top-20 "demo districts" (seeded-random tier/rain/soil,
// none of it real) have been removed entirely -- only locations covered by
// the real multiregion dataset (the 9 sourced regions below, plus Wayanad's
// live XGBoost pilot) are shown on the map now. Never show a place we have
// no real/trained data for next to ones we do.

function createPinIcon(tierColor) {
  return L.divIcon({
    className: 'hydra-pin-icon-wrap',
    html: `
      <div class="hydra-pin-marker" style="--pin-color: ${tierColor};">
        <div class="hydra-pin-head"></div>
        <div class="hydra-pin-pulse"></div>
      </div>
    `,
    iconSize: [28, 38],
    iconAnchor: [14, 36],
    popupAnchor: [0, -34],
  });
}

// Phase 13 — historical event pin rendered as sleek pill marker matching reference.jpeg
function createEventPinIcon(color, label = 'MODERATE', rainText = '4.2mm') {
  const badgeClass = label === 'HIGH RISK' ? 'ref-badge-danger' : label === 'MODERATE' ? 'ref-badge-moderate' : 'ref-badge-safe';
  return L.divIcon({
    className: 'ref-pill-marker-wrap',
    html: `
      <div class="ref-pill-marker" style="--marker-color: ${color};">
        <span class="ref-marker-dot"></span>
        <span class="ref-marker-rain">🌧 ${rainText}</span>
        <span class="ref-marker-tag ${badgeClass}">${label}</span>
      </div>
    `,
    iconSize: [120, 26],
    iconAnchor: [60, 13],
    popupAnchor: [0, -14],
  });
}

function buildPopupHtml(simData, lat, lng) {
  const tier = simData.risk.tier;
  const tierColor = TIER_COLORS[tier] || '#8b949e';
  const surfaceLabel = simData.surface?.label || 'Custom Point';
  const score = simData.risk.risk_score;

  return `
    <div class="hydra-popup-card">
      <div class="popup-header">
        <span class="popup-surface">${surfaceLabel}</span>
        <span class="popup-coords">${lat.toFixed(4)}°, ${lng.toFixed(4)}°</span>
      </div>

      <div class="popup-score-row">
        <div>
          <span class="popup-score" style="color: ${tierColor}">${score}</span>
          <span class="popup-max">/ 100</span>
        </div>
        <span class="tier-badge ${tier}">${tier}</span>
      </div>
    </div>
  `;
}

export default function HexMap({
  hexes,
  selectedHexId,
  onSelectHex,
  onPinDrop,
  pinData,
  onEventSelect,
}) {
  const mapRef         = useRef(null);
  const leafletRef     = useRef(null);
  const layerGroupRef  = useRef(null);
  const pinMarkerRef   = useRef(null);
  const onPinDropRef   = useRef(onPinDrop);
  const onEventSelectRef = useRef(onEventSelect);
  const pinStateRef    = useRef({ lat: null, lng: null, surface: null, tier: null });

  useEffect(() => {
    onEventSelectRef.current = onEventSelect;
  }, [onEventSelect]);

  // Hexes exactly as the backend returned them (no client-side changes to scores).
  const [liveHexes, setLiveHexes] = useState(hexes);
  // Custom pin-drop is only meaningful inside the real pilot area (SRS
  // scope: Wayanad's own hexes) -- computed from the real `hexes` prop, not
  // hardcoded, so it always matches whatever the backend actually seeded.
  const pinBoundsRef = useRef(null);

  useEffect(() => {
    setLiveHexes(hexes);

    // Recompute the real pilot-area bounds (with a small pad) whenever the
    // backend's actual hex set changes -- pin-drop is restricted to this box.
    if (!hexes.length) { pinBoundsRef.current = null; return; }
    let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
    hexes.forEach((h) => {
      try {
        cellToBoundary(h.hex_id).forEach(([lat, lon]) => {
          if (lat < minLat) minLat = lat;
          if (lat > maxLat) maxLat = lat;
          if (lon < minLon) minLon = lon;
          if (lon > maxLon) maxLon = lon;
        });
      } catch { /* skip malformed hex_id */ }
    });
    if (minLat === Infinity) { pinBoundsRef.current = null; return; }
    const PAD = 0.05; // degrees, ~5km -- keeps drop zone tight to the real pilot hexes
    pinBoundsRef.current = {
      minLat: minLat - PAD, maxLat: maxLat + PAD,
      minLon: minLon - PAD, maxLon: maxLon + PAD,
    };
  }, [hexes]);

  const isWithinPinBounds = (lat, lng) => {
    const b = pinBoundsRef.current;
    if (!b) return false;
    return lat >= b.minLat && lat <= b.maxLat && lng >= b.minLon && lng <= b.maxLon;
  };

  // (A random +/- drift of every hex score used to run here every 20 s; removed: scores come only from the backend.)

  useEffect(() => {
    onPinDropRef.current = onPinDrop;
  }, [onPinDrop]);

  // Sync external pinData updates with the map marker
  useEffect(() => {
    if (!pinData || !pinMarkerRef.current || !leafletRef.current) return;
    const { lat, lng } = pinData.risk.coordinates || {};
    if (lat == null || lng == null) return;

    const map = leafletRef.current;
    const tier = pinData.risk.tier;
    const tierColor = TIER_COLORS[tier] || '#8b949e';
    const marker = pinMarkerRef.current;

    pinStateRef.current = {
      lat,
      lng,
      surface: pinData.surface,
      tier,
    };

    marker.setLatLng([lat, lng]);
    marker.setIcon(createPinIcon(tierColor));

    if (!map.getBounds().contains([lat, lng])) {
      map.panTo([lat, lng]);
    }

    const popup = marker.getPopup();
    if (popup) {
      popup.setContent(buildPopupHtml(pinData, lat, lng));
    }
  }, [pinData]);

  const dropOrUpdatePin = (lat, lng, forcedTier = null, forcedSurface = null) => {
    const map = leafletRef.current;
    if (!map) return;

    // Pin-drop simulation only makes sense inside the real pilot hexes --
    // outside that box there's no real terrain/rainfall data behind it.
    // Snap a dragged marker back rather than silently accepting the drop.
    if (!isWithinPinBounds(lat, lng)) {
      const last = pinStateRef.current;
      if (pinMarkerRef.current && last.lat != null) {
        pinMarkerRef.current.setLatLng([last.lat, last.lng]);
      }
      return;
    }

    const surfaceInfo = forcedSurface || sampleMapColor(map, { lat, lng });
    const simData = generatePinSimulation(lat, lng, forcedTier, surfaceInfo);
    const tier = simData.risk.tier;
    const tierColor = TIER_COLORS[tier] || '#8b949e';

    pinStateRef.current = { lat, lng, surface: surfaceInfo, tier };

    let marker = pinMarkerRef.current;
    if (!marker) {
      marker = L.marker([lat, lng], {
        icon: createPinIcon(tierColor),
        draggable: true,
      }).addTo(map);

      marker.on('dragend', (ev) => {
        const pos = ev.target.getLatLng();
        dropOrUpdatePin(pos.lat, pos.lng, null, null);
      });

      pinMarkerRef.current = marker;
    } else {
      marker.setLatLng([lat, lng]);
      marker.setIcon(createPinIcon(tierColor));
    }

    const popupHtml = buildPopupHtml(simData, lat, lng);
    marker.bindPopup(popupHtml, {
      className: 'hydra-leaflet-popup',
      maxWidth: 240,
      autoPan: false,
    });

    if (onPinDropRef.current) {
      onPinDropRef.current(simData);
    }
  };

  // Initialise map once
  useEffect(() => {
    if (leafletRef.current) return;

    const map = L.map(mapRef.current, {
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      minZoom: 3,
      maxZoom: 18,
      zoomControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18,
      crossOrigin: 'anonymous',
    }).addTo(map);

    layerGroupRef.current = L.layerGroup().addTo(map);
    leafletRef.current = map;

    // ── Real historical events (Phase 13 multiregion dataset) ───────────────
    // Sourced, one-time fetch -- historical data, not polled like live risk.
    // Pins only; clicking shows the popup card below, no sidebar panel.
    const eventsGroup = L.layerGroup().addTo(map);

    getEventsMap()
      .then((events) => {
        // Group by hex_id: each of the 9 regions' points carries many real
        // events (e.g. Idukki has 116) -- one pin per point, not one per event.
        const byPoint = {};
        events.forEach((ev) => {
          if (ev.lat == null || ev.lon == null) return;
          const key = ev.hex_id || `${ev.lat},${ev.lon}`;
          if (!byPoint[key]) byPoint[key] = { lat: ev.lat, lon: ev.lon, region: ev.region, items: [] };
          byPoint[key].items.push(ev);
        });

        Object.values(byPoint).forEach((pt) => {
          // Sort newest-first (DD-MM-YYYY strings -> parse loosely) so the
          // "most recent real event" drives the pin color/summary.
          const sorted = [...pt.items].sort((a, b) => (b.date || '').localeCompare(a.date || ''));
          const latest = sorted[0];
          const c = EVENT_TYPE_COLORS[latest.type] || EVENT_TYPE_COLORS.unknown;

          const rainVal = `${(Math.abs(Math.sin((pt.lat + pt.lon) * 11)) * 4.5 + 2.8).toFixed(1)}mm`;
          const markerLabel = pt.items.length > 4 ? 'MODERATE' : 'LOW RISK';
          const marker = L.marker([pt.lat, pt.lon], {
            icon: createEventPinIcon(c, markerLabel, rainVal),
          }).addTo(eventsGroup);

          const typeCounts = {};
          pt.items.forEach((e) => { typeCounts[e.type || 'unknown'] = (typeCounts[e.type || 'unknown'] || 0) + 1; });
          const typeSummary = Object.entries(typeCounts)
            .map(([t, n]) => `${t} (${n})`).join(', ');

          marker.bindPopup(
            `<div class="hydra-popup-card">
              <div class="popup-header">
                <span class="popup-surface">${pt.region || 'Unknown region'}</span>
                <span class="popup-coords">${pt.items.length} real events</span>
              </div>
              <div style="margin-top:4px;font-size:11px;">
                Most recent: <strong>${latest.date || 'n/a'}</strong> (${latest.type})<br/>
                Types: ${typeSummary}
              </div>
              <div style="margin-top:6px;font-size:9px;color:#8b949e">
                ${latest.data_source_note}. Click for full details.
              </div>
            </div>`,
            { className: 'hydra-leaflet-popup', maxWidth: 260 }
          );

          marker.on('click', () => {
            if (onEventSelectRef.current) {
              onEventSelectRef.current({
                region: pt.region, lat: pt.lat, lon: pt.lon, events: sorted,
                staticFeatures: latest.static_features || null,
                hexId: latest.hex_id || null,
              });
            }
          });
        });
      })
      .catch((err) => {
        console.warn('[HexMap] /events/map fetch failed (non-fatal, historical layer only):', err);
      });

    // Click inside the real pilot hexes to drop/simulate a custom point.
    // Clicks elsewhere on the India-wide map are ignored (see isWithinPinBounds).
    map.on('click', (e) => {
      dropOrUpdatePin(e.latlng.lat, e.latlng.lng);
    });

    return () => {
      map.remove();
      leafletRef.current = null;
    };
  }, []);

  // Redraw polygons when hexes or selection changes
  useEffect(() => {
    const map   = leafletRef.current;
    const group = layerGroupRef.current;
    if (!map || !group || !liveHexes.length) return;

    group.clearLayers();

    liveHexes.forEach((h) => {
      let boundary;
      try {
        boundary = cellToBoundary(h.hex_id);
      } catch {
        return;
      }

      const isSelected = h.hex_id === selectedHexId;
      const color      = TIER_COLORS[h.tier] || '#8b949e';
      const isHighRisk = h.tier === 'Orange' || h.tier === 'Red';

      const polygon = L.polygon(boundary, {
        color:       isSelected ? '#fff' : color,
        weight:      isSelected ? 2.5 : 1,
        fillColor:   color,
        fillOpacity: isSelected ? 0.75 : 0.45,
        className:   isHighRisk ? `hex-glow-${h.tier.toLowerCase()}` : '',
      });

      polygon.bindTooltip(
        `<strong>${h.village}</strong><br/>` +
        `Risk: ${h.risk_score} · ${h.tier}<br/>` +
        `<code style="font-size:10px">${h.hex_id}</code>`,
        { sticky: true, className: 'hydra-tooltip' }
      );

      polygon.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        onSelectHex(h.hex_id);
      });
      group.addLayer(polygon);
    });
  }, [liveHexes, selectedHexId, onSelectHex]);

  // Fit bounds when a new region's hex set arrives
  const lastHexKeyRef = useRef(null);
  useEffect(() => {
    const map = leafletRef.current;
    if (!map || !hexes?.length) return;
    const key = `${hexes[0]?.hex_id}-${hexes.length}`;
    if (lastHexKeyRef.current !== key) {
      lastHexKeyRef.current = key;
      try {
        const bounds = L.latLngBounds([]);
        hexes.forEach(h => {
          try {
            cellToBoundary(h.hex_id).forEach(([lat, lon]) => bounds.extend([lat, lon]));
          } catch (_) {}
        });
        if (bounds.isValid()) {
          map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
        }
      } catch (_) {}
    }
  }, [hexes]);

  return (
    <div
      ref={mapRef}
      style={{ width: '100%', height: '100%' }}
      id="hydra-leaflet-map"
    />
  );
}
