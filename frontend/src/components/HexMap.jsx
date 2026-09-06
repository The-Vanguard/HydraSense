/**
 * HexMap.jsx — Phase 12
 * Leaflet map with H3 hex polygons coloured by tier.
 * SRS §15: data from GET /risk/map
 * CLAUDE.md: Leaflet ONLY — never Mapbox.
 * h3-js used for client-side hex_id → lat/lng polygon conversion.
 */
import React, { useEffect, useRef, useCallback } from 'react';
import L from 'leaflet';
import { cellToBoundary } from 'h3-js';

const TIER_COLORS = {
  Green:  '#22c55e',
  Yellow: '#eab308',
  Orange: '#f97316',
  Red:    '#ef4444',
};

// Wayanad pilot cluster bounding box centre
const MAP_CENTER = [11.539, 76.056];
const MAP_ZOOM   = 13;

export default function HexMap({ hexes, selectedHexId, onSelectHex }) {
  const mapRef       = useRef(null);
  const leafletRef   = useRef(null);
  const layerGroupRef = useRef(null);

  // Initialise map once
  useEffect(() => {
    if (leafletRef.current) return;

    const map = L.map(mapRef.current, {
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      zoomControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18,
    }).addTo(map);

    layerGroupRef.current = L.layerGroup().addTo(map);
    leafletRef.current = map;

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
        // h3-js returns [[lat, lng], ...] — Leaflet expects same
        boundary = cellToBoundary(h.hex_id);
      } catch {
        return; // skip invalid hex_id
      }

      const isSelected = h.hex_id === selectedHexId;
      const color      = TIER_COLORS[h.tier] || '#8b949e';

      const polygon = L.polygon(boundary, {
        color:       isSelected ? '#fff' : color,
        weight:      isSelected ? 2.5 : 1,
        fillColor:   color,
        fillOpacity: isSelected ? 0.75 : 0.45,
      });

      // Tooltip
      polygon.bindTooltip(
        `<strong>${h.village}</strong><br/>` +
        `Risk: ${h.risk_score} · ${h.tier}<br/>` +
        `<code style="font-size:10px">${h.hex_id}</code>`,
        { sticky: true, className: 'hydra-tooltip' }
      );

      polygon.on('click', () => onSelectHex(h.hex_id));
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
