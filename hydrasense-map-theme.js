import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { GeoJsonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { cellToBoundary, cellToLatLng } from "h3-js";

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

export const TIERS = ["green", "yellow", "orange", "red"];
export const TIER = {
  green: hex("#10b981"),
  yellow: hex("#f59e0b"),
  orange: hex("#f97316"),
  red: hex("#ef4444"),
};
export const INK = hex("#0e1116");
export const EDGE = hex("#e3e8ee");
export const BLUE = hex("#2e7def");

export const basemapStyle = (dark = false) => ({
  version: 8,
  sources: {
    base: {
      type: "raster",
      tiles: ["a", "b", "c"].map(
        (s) => `https://${s}.basemaps.cartocdn.com/${dark ? "dark_nolabels" : "light_nolabels"}/{z}/{x}/{y}.png`
      ),
      tileSize: 256,
      attribution: "© OpenStreetMap contributors © CARTO",
    },
  },
  layers: [{ id: "base", type: "raster", source: "base" }],
});

export const tierFor = (d, mode) => {
  if (mode === "flood") return d.tier_flood;
  if (mode === "landslide") return d.tier_landslide;
  return TIERS[Math.max(TIERS.indexOf(d.tier_flood), TIERS.indexOf(d.tier_landslide))];
};

const desaturate = ([r, g, b], confidence) => {
  const k = 0.6 + 0.4 * Math.min(Math.max(confidence, 0), 1);
  const y = 0.299 * r + 0.587 * g + 0.114 * b;
  return [r, g, b].map((c) => Math.round(y + (c - y) * k));
};

const corner = (h3, i) => {
  const [lat, lng] = cellToLatLng(h3);
  const [x, y] = cellToBoundary(h3, true)[i];
  return [lng + (x - lng) * 0.72, lat + (y - lat) * 0.72];
};

export const hexLayer = (data, { mode = "compound", selected, onClick } = {}) =>
  new H3HexagonLayer({
    id: "risk-hex",
    data,
    pickable: true,
    filled: true,
    stroked: true,
    extruded: false,
    getHexagon: (d) => d.h3,
    getFillColor: (d) => [...desaturate(TIER[tierFor(d, mode)], d.confidence), 215],
    getLineColor: (d) => (d.h3 === selected ? INK : d.sensor_adjusted ? BLUE : [...EDGE, 140]),
    getLineWidth: (d) => (d.h3 === selected ? 3 : d.sensor_adjusted ? 2 : 1),
    lineWidthUnits: "pixels",
    updateTriggers: { getFillColor: [mode], getLineColor: [selected], getLineWidth: [selected] },
    onClick,
  });

export const resilienceLayer = (data) =>
  new ScatterplotLayer({
    id: "resilience-dot",
    data,
    getPosition: (d) => corner(d.h3, 0),
    getRadius: 5,
    radiusUnits: "pixels",
    stroked: true,
    lineWidthUnits: "pixels",
    getLineWidth: 1.5,
    getLineColor: INK,
    getFillColor: (d) => (d.instrumented ? INK : [255, 255, 255]),
  });

export const dualTierLayer = (data, mode) =>
  new ScatterplotLayer({
    id: "dual-tier-edge",
    data: mode === "compound" ? data.filter((d) => d.tier_flood !== d.tier_landslide) : [],
    getPosition: (d) => corner(d.h3, 3),
    getRadius: 4,
    radiusUnits: "pixels",
    getFillColor: (d) => TIER[TIERS[Math.min(TIERS.indexOf(d.tier_flood), TIERS.indexOf(d.tier_landslide))]],
    stroked: true,
    getLineColor: [255, 255, 255],
    getLineWidth: 1,
    lineWidthUnits: "pixels",
  });

export const villageLayer = (data) =>
  new GeoJsonLayer({
    id: "villages",
    data,
    pickable: true,
    filled: false,
    stroked: true,
    getLineColor: [...INK, 200],
    getLineWidth: 1.5,
    lineWidthUnits: "pixels",
    lineJointRounded: true,
  });
