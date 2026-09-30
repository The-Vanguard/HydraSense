/**
 * Dashboard.jsx — HydraSense v2 "Disaster Intelligence & Warning Center".
 *
 * Tabs: Overview | GIS Risk Map | Alerts | Event Replay | Analytics.  Every number comes from the backend;
 * a missing value is shown with its reason.  The Response Unit role gets the narrower field view.
 * The previous console is still reachable at ?classic=1.
 */
import React, { useMemo, useState } from 'react';
import './v2.css';
import useDashboard, { NATIONAL } from './useDashboard';
import { TopBar, NoticeBar, Footer } from './Shell';
import Kpis from './Kpis';
import Sidebar from './Sidebar';
import MapCard from './MapCard';
import VillageCard from './VillageCard';
import { EventReplay, ScenarioSimulator, ActiveAlerts } from './BottomPanels';
import { REGION_NAMES } from './tiers';

import VillagePanel from '../components/VillagePanel';
import ConfidenceFactors from '../components/ConfidenceFactors';
import AlertFeed from '../components/AlertFeed';
import CitizenPreviewPanel from '../components/CitizenPreviewPanel';
import IncidentActionPlan from '../components/IncidentActionPlan';
import ValidationPanel from '../components/ValidationPanel';
import LoroPanel from '../components/LoroPanel';
import ResponseUnitView from '../components/ResponseUnitView';
import ManualScenarioPanel from '../components/ManualScenarioPanel';

export default function Dashboard() {
  const d = useDashboard();
  const [tab, setTab] = useState('overview');
  const [hazard, setHazard] = useState('compound');
  const [role, setRole] = useState('Decision Authority');
  const [inspect, setInspect] = useState(false);

  const lastUpdated = useMemo(() => d.regionStatus.map((r) => r.last_updated).filter(Boolean).sort().pop() || null,
    [d.regionStatus]);
  const liveScores = lastUpdated && Date.now() - new Date(lastUpdated).getTime() < 20 * 60 * 1000;
  const exerciseOpen = d.gates.some((g) => g.exercise);
  const simulatedPresent = d.hexes.some((h) => h.data_source === 'sensor') || exerciseOpen;
  const rainSource = d.risk?.data_source || null;
  const selectedHex = d.hexes.find((h) => h.hex_id === d.selectedHexId) || null;
  const currentRegion = { region_code: d.region, region_label: REGION_NAMES[d.region] };

  if (role === 'Response Unit') {
    return (
      <div className="hs2">
        <TopBar tab={tab} onTab={setTab} alertCount={d.gates.length} backendUp={d.backendUp} liveScores={liveScores}
                region={d.region} onRegion={d.selectRegion} role={role} onRole={setRole} />
        <NoticeBar lastUpdated={lastUpdated} simulatedPresent={simulatedPresent} exerciseOpen={exerciseOpen} />
        <div className="hs2-scroll hs2-legacy"><ResponseUnitView hexes={d.hexes} alerts={d.gates} region={currentRegion} /></div>
        <Footer rainSource={rainSource} />
      </div>
    );
  }

  return (
    <div className="hs2">
      <TopBar tab={tab} onTab={setTab} alertCount={d.gates.length} backendUp={d.backendUp} liveScores={liveScores}
              region={d.region} onRegion={d.selectRegion} role={role} onRole={setRole} />
      <NoticeBar lastUpdated={lastUpdated} simulatedPresent={simulatedPresent} exerciseOpen={exerciseOpen} />
      {exerciseOpen && <div className="hs2-exercise">Simulated feed. Exercise alert, nothing is being sent.</div>}

      <div className="hs2-scroll">
        <div className="hs2-titlebar">
          <span style={{ fontSize: 26 }} aria-hidden="true">🛡</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1>Disaster Intelligence &amp; Warning Center</h1>
            <div className="sub">Integrated risk monitoring · multi-hazard (landslide + flash flood) · village / ward level</div>
          </div>
          <select className="hs2-select" style={{ minWidth: 220 }} value={d.region} onChange={(e) => d.selectRegion(e.target.value)}>
            {Object.entries(REGION_NAMES).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
          <button className="hs2-btn primary" onClick={() => setTab('map')}>🗺 Open GIS map</button>
        </div>

        {tab === 'overview' && (
          <>
            <Kpis summary={d.summary} summaryError={d.summaryError} regionStatus={d.regionStatus}
                  region={d.region} national={d.national} />
            <div className="hs2-main">
              <Sidebar region={d.region} onRegion={d.selectRegion} rainSource={rainSource}
                       soilSat={d.risk?.inputs?.soil_saturation_ratio} wsMessages={d.wsMessages}
                       onInspect={() => setInspect(true)} onOnboarded={d.selectRegion} />
              <MapCard d={d} hazard={hazard} onHazard={setHazard} onOpenRegion={d.selectRegion} />
              <VillageCard d={d} onOpenAlerts={() => setTab('alerts')} />
            </div>
            <div className="hs2-bottom">
              <EventReplay d={d} />
              <ScenarioSimulator d={d} />
              <ActiveAlerts d={d} onViewAll={() => setTab('alerts')} />
            </div>
          </>
        )}

        {tab === 'map' && (
          <div className="hs2-page-grid">
            <MapCard d={d} hazard={hazard} onHazard={setHazard} onOpenRegion={d.selectRegion} tall />
            <div className="hs2-legacy">
              {d.national
                ? <div className="hs2-card"><div className="hs2-empty">Pick a region (map circle or selector) to see its village table.</div></div>
                : <VillagePanel region={d.region} />}
              <ConfidenceFactors hexId={d.selectedHexId} />
            </div>
          </div>
        )}

        {tab === 'alerts' && (
          <div className="hs2-page-grid">
            <div>
              <ActiveAlerts d={d} full />
              <div className="hs2-legacy" style={{ marginTop: 12 }}><AlertFeed /></div>
            </div>
            <div className="hs2-legacy">
              <IncidentActionPlan selectedHex={selectedHex} region={currentRegion} />
              <CitizenPreviewPanel selectedHex={selectedHex} region={currentRegion} />
            </div>
          </div>
        )}

        {tab === 'replay' && (
          <div className="hs2-page-grid">
            <EventReplay d={d} full />
            <div className="hs2-card">
              <div className="hs2-card-title">About replays</div>
              <div className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
                A replay feeds the real hourly rainfall (ERA5-derived) of the 24 hours before a recorded event through
                the same physics-first index as the live map, using the event hex's onboarded terrain. It is a back-test
                view, not a validated result: soil saturation and 72 h antecedent rain are not in the historical series
                and are reported as missing. Across 510 replayable events, 14 reach Orange or Red, consistent with the
                earlier finding that rainfall alone separates events weakly.
              </div>
            </div>
          </div>
        )}

        {tab === 'analytics' && (
          <div className="hs2-page-grid hs2-legacy">
            <div><ValidationPanel /><LoroPanel /></div>
            <div>
              <ConfidenceFactors hexId={d.selectedHexId} />
              <div className="hs2-card">
                <div className="hs2-card-title">Scoring method</div>
                <div className="muted" style={{ fontSize: 12, lineHeight: 1.6 }}>
                  Physics-first hazard index (v2 Sec. 15.10 fallback): rainfall trigger × slope-stability susceptibility
                  for landslides, HAND term for floods; tiers at 30 / 55 / 75. It is an engineered, uncalibrated index,
                  not a probability. ML fusion is not used live because it did not beat rainfall alone on the event set.
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <Footer rainSource={rainSource} />

      {inspect && (
        <div role="dialog" aria-modal="true" onClick={() => setInspect(false)}
             style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', zIndex: 50, display: 'flex',
                      justifyContent: 'center', alignItems: 'flex-start', padding: '40px 16px', overflow: 'auto' }}>
          <div className="hs2-legacy" onClick={(e) => e.stopPropagation()} style={{ width: 'min(720px, 100%)' }}>
            <div style={{ textAlign: 'right', marginBottom: 6 }}>
              <button className="hs2-btn small" onClick={() => setInspect(false)}>Close</button>
            </div>
            <ManualScenarioPanel onClose={() => setInspect(false)} />
          </div>
        </div>
      )}
    </div>
  );
}

export { NATIONAL };
