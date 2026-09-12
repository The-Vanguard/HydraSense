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

// Phase 13 — real sourced historical events. Deliberately NOT reusing
// TIER_COLORS: that palette means "live risk tier," these are historical
// records with no live model output. Neutral blue/purple family instead.
const EVENT_TYPE_COLORS = {
  flash_flood:     '#38bdf8',
  riverine_flood:  '#818cf8',
  landslide_only:  '#a78bfa',
  ambiguous:       '#94a3b8',
  unknown:         '#64748b',
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

// Rudraprayag, Chamoli, Idukki, and Wayanad were removed from this list
// (Phase 13) -- real sourced historical event data now covers them (see
// EVENT_TYPE_COLORS layer below); keeping a fabricated dot at the same
// coordinates as real data would be misleading.
const DEMO_DISTRICTS = [
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
  { name: 'Shimla',        state: 'Himachal Pradesh', lat: 31.104, lon: 77.173, baseTier: 'Orange', isroRank: 'Top 20' },
  { name: 'Ernakulam',     state: 'Kerala',           lat:  9.982, lon: 76.300, baseTier: 'Yellow', isroRank: 'Top 20', fixedTier: 'Green' },
  { name: 'Mandi',         state: 'Himachal Pradesh', lat: 31.707, lon: 76.932, baseTier: 'Orange', isroRank: 'Top 20' },
  { name: 'Udhampur',      state: 'J&K',              lat: 32.916, lon: 75.141, baseTier: 'Yellow', isroRank: 'Top 20' },
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

// Phase 13 — historical event pin. Same shape, no pulse (not live).
function createEventPinIcon(color) {
  return L.divIcon({
    className: 'hydra-pin-icon-wrap',
    html: `
      <div class="hydra-event-pin-marker" style="--pin-color: ${color};">
        <div class="hydra-event-pin-head"></div>
      </div>
    `,
    iconSize: [22, 30],
    iconAnchor: [11, 28],
    popupAnchor: [0, -26],
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
  const demoLayerRef   = useRef(null);
  const eventsLayerRef = useRef(null);
  const pinMarkerRef   = useRef(null);
  const onPinDropRef   = useRef(onPinDrop);
  const onEventSelectRef = useRef(onEventSelect);
  const pinStateRef    = useRef({ lat: null, lng: null, surface: null, tier: null });

  useEffect(() => {
    onEventSelectRef.current = onEventSelect;
  }, [onEventSelect]);

  // Auto-escalating hex scores: shift each hex score up slightly every 20s
  // to simulate a live ingestion cycle updating risk in real time
  const [liveHexes, setLiveHexes] = useState(hexes);
  const escalateRef = useRef(null);

  useEffect(() => {
    setLiveHexes(hexes);
  }, [hexes]);

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

      // On click: generate full simulation payload (instant 0ms) matching district tier & score
      dot.on('click', (e) => {
        L.DomEvent.stopPropagation(e);

        const surfaceInfo = { surface: 'district', label: `${d.name}, ${d.state}` };
        const simData = generatePinSimulation(d.lat, d.lon, d.tier, surfaceInfo);
        
        // Pin exact district score & village metadata
        simData.risk.risk_score = d.score;
        simData.risk.village = `${d.name}, ${d.state} (ISRO Rank #${d.isroRank})`;
        simData.surface = { label: `${d.name}, ${d.state}` };

        const tierColor = TIER_COLORS[d.tier] || '#8b949e';

        // Move or create the pin marker at district location
        let marker = pinMarkerRef.current;
        if (!marker) {
          marker = L.marker([d.lat, d.lon], {
            icon: createPinIcon(tierColor),
            draggable: true,
          }).addTo(map);
          marker.on('dragend', (ev) => {
            const pos = ev.target.getLatLng();
            dropOrUpdatePin(pos.lat, pos.lng, null, null);
          });
          pinMarkerRef.current = marker;
        } else {
          marker.setLatLng([d.lat, d.lon]);
          marker.setIcon(createPinIcon(tierColor));
        }

        const popupHtml = buildPopupHtml(simData, d.lat, d.lon);
        marker.bindPopup(popupHtml, {
          className: 'hydra-leaflet-popup',
          maxWidth: 240,
          autoPan: false,
        });

        pinStateRef.current = {
          lat: d.lat,
          lng: d.lon,
          surface: simData.surface,
          tier: d.tier,
        };

        if (onPinDropRef.current) {
          onPinDropRef.current(simData);
        }
      });
    });

    // ── Real historical events (Phase 13 multiregion dataset) ───────────────
    // Sourced, one-time fetch -- historical data, not polled like live risk.
    const eventsGroup = L.layerGroup().addTo(map);
    eventsLayerRef.current = eventsGroup;

    getEventsMap()
      .then((events) => {
        // Group by hex_id: each of the 9 regions' points carries many real
        // events (e.g. Idukki has 116) -- one pin per point, not one per
        // event, matching what the user asked to see ("pin those 9 places").
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

          const marker = L.marker([pt.lat, pt.lon], {
            icon: createEventPinIcon(c),
          }).addTo(eventsGroup);

          const typeCounts = {};
          pt.items.forEach((e) => { typeCounts[e.type || 'unknown'] = (typeCounts[e.type || 'unknown'] || 0) + 1; });
          const typeSummary = Object.entries(typeCounts)
            .map(([t, n]) => `${t} (${n})`).join(', ');

          marker.bindPopup(
            `<div class="hydra-popup-card">
              <div class="popup-header">
                <span class="popup-surface">&#128204; ${pt.region || 'Unknown region'}</span>
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

          marker.on('click', (e) => {
            L.DomEvent.stopPropagation(e);
            if (onEventSelectRef.current) {
              onEventSelectRef.current({
                region: pt.region, lat: pt.lat, lon: pt.lon, events: sorted,
                staticFeatures: latest.static_features || null,
              });
            }
          });
        });
      })
      .catch((err) => {
        console.warn('[HexMap] /events/map fetch failed (non-fatal, historical layer only):', err);
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
