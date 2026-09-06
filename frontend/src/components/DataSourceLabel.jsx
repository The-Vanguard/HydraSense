/**
 * DataSourceLabel.jsx — HydraSense Top Banner
 * Displays system brand, active region context, and Live status banner.
 */
import React from 'react';

export default function DataSourceLabel({ dataSource, stage }) {
  const isLive = dataSource !== 'cached_demo';

  return (
    <div className="datasource-banner">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#58a6ff', letterSpacing: '-0.3px' }}>
          HydraSense
        </span>
        <span style={{ fontSize: 11, color: '#484f58' }}>
          Early Warning System — Landslide &amp; Inundation Monitoring
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        {stage && (
          <span style={{ fontSize: 11, color: '#8b949e' }}>
            Region: <strong style={{ color: '#e6edf3' }}>{stage}</strong>
          </span>
        )}
        <span className={isLive ? 'datasource-live' : 'datasource-cached'}>
          {isLive ? '● Data source: LIVE' : '⚠ Data source: CACHED DEMO'}
        </span>
      </div>
    </div>
  );
}
