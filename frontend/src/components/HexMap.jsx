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

// Map center: India overview so all 20 demo districts are visible
const MAP_CENTER = [22, 82];
const MAP_ZOOM   = 5;

// ── Demo Districts (ISRO Landslide Atlas 2023 — top 20 by risk rank) ────────
// Values are seeded-random, September post-monsoon biased. NOT from live model.
const _TIERS = ['Green', 'Yellow', 'Orange', 'Red'];
const _BS    = { Green: 20, Yellow: 42, Orange: 64, Red: 88 };
function _mkRng(seed) {
  let s = seed >>> 0;
  return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967295; };
}
const _rng = _mkRng(20260907);

const DEMO_DISTRICTS = [
  { name: 'Rudraprayag',   state: 'Uttarakhand',      lat: 30.284, lon: 78.981, baseTier: 'Orange', isroRank: '#1' },
  { name: 'Tehri Garhwal', state: 'Uttarakhand',      lat: 30.378, lon: 78.480, baseTier: 'Orange', isroRank: '#2' },
  { name: 'Thrissur',      state: 'Kerala',           lat: 10.527, lon: 76.214, baseTier: 'Yellow', isroRank: 'Top 10', fixedTier: 'Yellow' },
  { name: 'Rajouri',       state: 'J&K',              lat: 33.377, lon: 74.303, baseTier: 'Orange', isroRank: 'Top 10', fixedTier: 'Orange' },
  { name: 'Palakkad',      state: 'Kerala',           lat: 10.776, lon: 76.653, baseTier: 'Yellow', isroRank: 'Top 10', fixedTier: 'Green' },
  { name: 'Poonch',        state: 'J&K',              lat: 33.772, lon: 74.093, baseTier: 'Orange', isroRank: 'Top 10' },
  { name: 'Malappuram',    state: 'Kerala',           lat: 11.073, lon: 76.074, baseTier: 'Yellow', isroRank: 'Top 15', fixedTier: 'Green' },
  { name: 'South Sikkim',  state: 'Sikkim',           lat: 27.147, lon: 88.429, baseTier: 'Orange', isroRank: 'Top 15' },
  { name: 'East Sikkim',   state: 'Sikkim',           lat: 27.334, lon: 88.611, baseTier: 'Orange', isroRank: 'Top 15' },
  { name: 'Kozhikode',     state: 'Kerala',           lat: 11.258, lon: 75.780, baseTier: 'Yellow', isroRank: 'Top 15', fixedTier: 'Green' },
  { name: 'Imphal West',   state: 'Manipur',          lat: 24.817, lon: 93.936, baseTier: 'Yellow', isroRank: 'Top 20' },
  { name: 'Kodagu',        state: 'Karnataka',        lat: 12.421, lon: 75.739, baseTier: 'Yellow', isroRank: 'Top 20' },
  { name: 'Wayanad',       state: 'Kerala',           lat: 11.607, lon: 76.082, baseTier: 'Red',    isroRank: 'Top 20', fixedTier: 'Yellow' },
  { name: 'Shimla',        state: 'Himachal Pradesh', lat: 31.104, lon: 77.173, baseTier: 'Orange', isroRank: 'Top 20' },
  { name: 'Ernakulam',     state: 'Kerala',           lat:  9.982, lon: 76.300, baseTier: 'Yellow', isroRank: 'Top 20', fixedTier: 'Green' },
  { name: 'Mandi',         state: 'Himachal Pradesh', lat: 31.707, lon: 76.932, baseTier: 'Orange', isroRank: 'Top 20' },
  { name: 'Udhampur',      state: 'J&K',              lat: 32.916, lon: 75.141, baseTier: 'Yellow', isroRank: 'Top 20' },
  { name: 'Idukki',        state: 'Kerala',           lat:  9.849, lon: 76.972, baseTier: 'Orange', isroRank: 'Top 20', fixedTier: 'Yellow' },
  { name: 'Chamoli',       state: 'Uttarakhand',      lat: 30.409, lon: 79.321, baseTier: 'Red',    isroRank: 'Top 20' },
  { name: 'West Sikkim',   state: 'Sikkim',           lat: 27.298, lon: 88.267, baseTier: 'Orange', isroRank: 'Top 20' },
].map(d => {
  // Kerala districts are pinned to Green/Yellow (fixedTier). Others use seeded RNG.
  const idx = _TIERS.indexOf(d.baseTier), r = _rng();
  const tier = d.fixedTier || ((r < 0.35 && idx > 0) ? _TIERS[idx - 1] : (r > 0.90 && idx < 3) ? _TIERS[idx + 1] : d.baseTier);
  const score = Math.round(_BS[tier] + (_rng() - 0.5) * 14);
  const rain  = ({ Green: () => (_rng() * 8).toFixed(1), Yellow: () => (9 + _rng() * 18).toFixed(1), Orange: () => (28 + _rng() * 32).toFixed(1), Red: () => (65 + _rng() * 35).toFixed(1) })[tier]();
  const soil  = ({ Green: () => (0.18 + _rng() * 0.18).toFixed(2), Yellow: () => (0.38 + _rng() * 0.22).toFixed(2), Orange: () => (0.60 + _rng() * 0.16).toFixed(2), Red: () => (0.78 + _rng() * 0.20).toFixed(2) })[tier]();
  return { ...d, tier, score, rain, soil };
});

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
  const demoLayerRef   = useRef(null);
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

    // ── Demo district markers (ISRO top-20, September demo values) ──────────
    const demoGroup = L.layerGroup().addTo(map);
    demoLayerRef.current = demoGroup;

    DEMO_DISTRICTS.forEach(d => {
      const c = TIER_COLORS[d.tier] || '#8b949e';
      // Outer halo ring
      L.circleMarker([d.lat, d.lon], {
        radius: 13, color: c, weight: 2, opacity: 0.55,
        fillColor: c, fillOpacity: 0.12, interactive: false,
      }).addTo(demoGroup);
      // Inner filled dot
      const dot = L.circleMarker([d.lat, d.lon], {
        radius: 5.5, color: '#ffffff', weight: 1.5,
        fillColor: c, fillOpacity: 1,
      }).addTo(demoGroup);
      dot.bindPopup(
        `<div class="hydra-popup-card">
          <div class="popup-header">
            <span class="popup-surface">&#128205; ${d.name}, ${d.state}</span>
            <span class="popup-coords">ISRO ${d.isroRank}</span>
          </div>
          <div class="popup-score-row">
            <div>
              <span class="popup-score" style="color:${c}">${d.score}</span>
              <span class="popup-max">/ 100</span>
            </div>
            <span class="tier-badge ${d.tier}">${d.tier}</span>
          </div>
          <div style="margin-top:6px;font-size:10px;color:#8b949e">
            Rain 24h: ${d.rain} mm &nbsp;&bull;&nbsp; Soil sat: ${d.soil}
          </div>
        </div>`,
        { className: 'hydra-leaflet-popup', maxWidth: 240 }
      );
    });

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
