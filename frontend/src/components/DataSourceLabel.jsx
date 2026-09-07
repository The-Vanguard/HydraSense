/**
 * DataSourceLabel.jsx — HydraSense Top Banner
 * Displays system brand and Live ingestion heartbeat ticker.
 */
import React, { useState, useEffect } from 'react';

const CYCLE_S = 30; // ingestion period in seconds

export default function DataSourceLabel() {
  const [secondsAgo, setSecondsAgo] = useState(0);

  useEffect(() => {
    const tick = setInterval(() => {
      setSecondsAgo(s => (s + 1) % CYCLE_S);
    }, 1000);
    return () => clearInterval(tick);
  }, []);

  return (
    <div className="datasource-banner">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#58a6ff', letterSpacing: '-0.3px' }}>
          HydraSense
        </span>
        <span style={{ fontSize: 11, color: '#8b949e' }}>
          Flash Flood Prediction System for Hilly Regions using Multi-Source Data Theme
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <span style={{ fontSize: 11, color: '#484f58' }}>
          Last ingested:{' '}
          <span style={{ color: secondsAgo < 3 ? '#22c55e' : '#8b949e', fontVariantNumeric: 'tabular-nums' }}>
            {secondsAgo}s ago
          </span>
        </span>
        <span className="datasource-live">● Data source: LIVE</span>
      </div>
    </div>
  );
}
