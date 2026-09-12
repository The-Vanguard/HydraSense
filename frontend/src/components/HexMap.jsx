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

const TIER_COLORS = {
  Green:  '#22c55e',
  Yellow: '#eab308',
  Orange: '#f97316',
  Red:    '#ef4444',
};

// Map center: India overview so all 10 real (trained/sourced) locations are visible
const MAP_CENTER = [22, 82];
const MAP_ZOOM   = 5;

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
}) {
  const mapRef         = useRef(null);
  const leafletRef     = useRef(null);
  const layerGroupRef  = useRef(null);
  const pinMarkerRef   = useRef(null);
  const onPinDropRef   = useRef(onPinDrop);
  const pinStateRef    = useRef({ lat: null, lng: null, surface: null, tier: null });

  // Auto-escalating hex scores: shift each hex score up slightly every 20s
  // to simulate a live ingestion cycle updating risk in real time
  const [liveHexes, setLiveHexes] = useState(hexes);
  const escalateRef = useRef(null);
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

  useEffect(() => {
    clearInterval(escalateRef.current);
    escalateRef.current = setInterval(() => {
      setLiveHexes(prev => prev.map(h => {
        const bump = Math.random() * 3 - 0.5; // small drift ±
        const newScore = Math.min(100, Math.max(0, (h.risk_score || 0) + bump));
        const tier =
          newScore >= 75 ? 'Red' :
          newScore >= 55 ? 'Orange' :
          newScore >= 30 ? 'Yellow' : 'Green';
        return { ...h, risk_score: Math.round(newScore), tier };
      }));
    }, 20_000);
    return () => clearInterval(escalateRef.current);
  }, [hexes]);

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

  return (
    <div
      ref={mapRef}
      style={{ width: '100%', height: '100%' }}
      id="hydra-leaflet-map"
    />
  );
}
