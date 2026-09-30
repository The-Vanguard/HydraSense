/**
 * MapCard.jsx — hazard toggle, village search, map (deck.gl or Leaflet), degraded-input banner.
 * National view shows one marker per onboarded region coloured by its worst current tier.
 */
import React, { useMemo, useState } from 'react';
import DeckHexMap from '../components/DeckHexMap';
import HexMap from '../components/HexMap';
import { TIER_COLOR, TIER_WORD, REGION_NAMES } from './tiers';

const HAZARDS = [['compound', 'Compound'], ['flood', 'Flood'], ['landslide', 'Landslide']];

export default function MapCard({
  d, hazard, onHazard, onOpenRegion, tall = false,
}) {
  const [engine, setEngine] = useState('deck');
  const [q, setQ] = useState('');
  const light = (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme')) !== 'dark';

  const markers = useMemo(() => d.regionStatus.filter((r) => r.center).map((r) => ({
    region_code: r.region_code, label: REGION_NAMES[r.region_code] || r.region_code,
    lat: r.center.lat, lon: r.center.lon, worst_tier: r.worst_tier,
  })), [d.regionStatus]);

  const matches = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    if (d.national) {
      return markers.filter((m) => m.label.toLowerCase().includes(s)).slice(0, 8)
        .map((m) => ({ kind: 'region', key: m.region_code, name: m.label, tier: m.worst_tier }));
    }
    return (d.villages?.villages || []).filter((v) => (v.name || '').toLowerCase().includes(s)).slice(0, 10)
      .map((v) => ({ kind: 'village', key: v.village_id, name: v.name, tier: v.alert_tier }));
  }, [q, d.national, d.villages, markers]);

  const counts = d.hexes.reduce((m, h) => {
    const k = typeof h.data_source === 'string' ? h.data_source : 'unknown';
    m[k] = (m[k] || 0) + 1; return m;
  }, {});
  const sensorTagged = counts.sensor || 0;
  const nonLive = Object.entries(counts).filter(([k]) => !/live/.test(k) && k !== 'sensor');

  const props = {
    hexes: d.hexes, selectedHexId: d.selectedHexId, onSelectHex: d.selectHex, events: [],
    hazardMode: hazard, regionMarkers: d.national ? markers : [], onRegionClick: onOpenRegion,
    nationalView: d.national, light,
  };

  return (
    <div className={`hs2-card hs2-mapcard${tall ? ' tall' : ''}`}>
      <div className="hs2-maptools">
        <div className="hs2-seg" role="tablist" aria-label="Hazard">
          {HAZARDS.map(([k, label]) => (
            <button key={k} className={hazard === k ? 'is-active' : ''} onClick={() => onHazard(k)}>{label}</button>
          ))}
        </div>
        <button className="hs2-btn small" onClick={() => setEngine((e) => (e === 'deck' ? 'leaflet' : 'deck'))}
                title="Switch map engine">{engine === 'deck' ? 'deck.gl' : 'Leaflet'}</button>
        <div className="hs2-search">
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder={d.national ? 'Search region…' : 'Search village / ward…'} aria-label="Search" />
          {matches.length > 0 && (
            <div className="hs2-search-results">
              {matches.map((m) => (
                <button key={m.key} onClick={() => {
                  setQ('');
                  if (m.kind === 'region') onOpenRegion(m.key);
                  else d.selectVillage({ village_id: m.key, region_code: d.region });
                }}>
                  <span className="hs2-swatch" style={{ background: TIER_COLOR[m.tier] || '#94a3b8', marginTop: 3 }} />
                  <span>{m.name}</span>
                  <span className="faint" style={{ marginLeft: 'auto' }}>{m.tier ? TIER_WORD[m.tier] : 'not scored'}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="hs2-mapwrap">
        <div className="hs2-mapbanner">
          {!d.national && d.hexes.length === 0 && (
            <div className="hs2-banner">No current scores for this region yet. Scores appear after the next
              scoring cycle for it; nothing is estimated in the meantime.</div>
          )}
          {sensorTagged > 0 && (
            <div className="hs2-banner" style={{ marginTop: 4 }}>{sensorTagged} of {d.hexes.length} hexes are tagged
              "sensor", but no sensors are deployed: they were scored from simulated observations.</div>
          )}
          {nonLive.map(([k, n]) => (
            <div key={k} className="hs2-banner" style={{ marginTop: 4 }}>
              {k === 'unavailable'
                ? `${n} of ${d.hexes.length} hexes have no rainfall: the live Open-Meteo call failed and there is no recent reading nearby, so rain is counted as a missing input.`
                : k === 'open_meteo_cached'
                  ? `${n} of ${d.hexes.length} hexes use the last good Open-Meteo reading for their area (under 6 h old) because the live call failed; confidence is lower.`
                  : `Rainfall degraded: ${n} of ${d.hexes.length} hexes scored from "${k}" (not live); confidence is lower.`}
            </div>
          ))}
        </div>
        {engine === 'deck' ? <DeckHexMap {...props} /> : <HexMap {...props} />}
      </div>
    </div>
  );
}
