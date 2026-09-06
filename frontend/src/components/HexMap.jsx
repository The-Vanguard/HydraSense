/**
 * HexMap.jsx — HydraSense Geospatial Map Component
 * Interactive Leaflet map with H3 hexagonal polygons and draggable point analysis.
 * Supports regional hazard evaluation based on terrain classification,
 * surface characteristics, and seasonal dynamics.
 */
import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import { cellToBoundary } from 'h3-js';
import { sampleMapColor, generatePinSimulation } from '../utils/pinSimulation';

const TIER_COLORS = {
  Green:  '#22c55e',
  Yellow: '#eab308',
  Orange: '#f97316',
  Red:    '#ef4444',
};

// Default center: broader Kerala context; minZoom allows free exploration
const MAP_CENTER = [11.539, 76.056];
const MAP_ZOOM   = 7;

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

    // Click anywhere on map to drop pin and simulate
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
    if (!map || !group || !hexes.length) return;

    group.clearLayers();

    hexes.forEach((h) => {
      let boundary;
      try {
        boundary = cellToBoundary(h.hex_id);
      } catch {
        return;
      }

      const isSelected = h.hex_id === selectedHexId;
      const color      = TIER_COLORS[h.tier] || '#8b949e';

      const polygon = L.polygon(boundary, {
        color:       isSelected ? '#fff' : color,
        weight:      isSelected ? 2.5 : 1,
        fillColor:   color,
        fillOpacity: isSelected ? 0.75 : 0.45,
      });

      polygon.bindTooltip(
        `<strong>${h.village}</strong><br/>` +
        `Risk: ${h.risk_score} · ${h.tier}<br/>` +
        `<code style="font-size:10px">${h.hex_id}</code>`,
        { sticky: true, className: 'hydra-tooltip' }
      );

      polygon.on('click', (e) => {
        L.DomEvent.stopPropagation(e); // prevent map click from dropping pin
        onSelectHex(h.hex_id);
      });
      group.addLayer(polygon);
    });
  }, [hexes, selectedHexId, onSelectHex]);

  return (
    <div
      ref={mapRef}
      style={{ width: '100%', height: '100%' }}
      id="hydra-leaflet-map"
    />
  );
}
