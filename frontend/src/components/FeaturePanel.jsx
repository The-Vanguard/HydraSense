/**
 * FeaturePanel.jsx — Phase 12
 * Horizontal bar chart of top_contributing_features for selected hex.
 * Bars animate in from 0 on each new data load.
 */
import React, { useState, useEffect } from 'react';

const FEATURE_LABELS = {
  rainfall_1h:                    'Rainfall 1h',
  rainfall_3h:                    'Rainfall 3h',
  rainfall_6h:                    'Rainfall 6h',
  rainfall_24h:                   'Rainfall 24h',
  rainfall_72h_antecedent:        'Rainfall 72h antecedent',
  rain_intensity_mm_hr:           'Rain intensity (mm/hr)',
  antecedent_precipitation_index: 'Antecedent precip. index',
  soil_saturation_ratio:          'Soil saturation (proxy)',
  factor_of_safety:               'Factor of safety',
  factor_of_safety_min:           'FS min (band)',
  factor_of_safety_max:           'FS max (band)',
  simulated_ffgs_signal:          'Simulated FFGS signal',
  simulated_gsi_signal:           'Simulated GSI signal',
  iot_anomaly_flag:               'IoT anomaly flag',
  slope_deg:                      'Slope (°)',
  aspect:                         'Aspect',
  elevation:                      'Elevation (m)',
  TWI:                            'Topographic wetness index',
  TRI:                            'Terrain roughness index',
  distance_to_stream_m:           'Distance to stream (m)',
  drainage_density:               'Drainage density',
  ndvi_mean:                      'NDVI mean',
  land_use_class:                 'Land use class',
  gsi_susceptibility_class:       'GSI susceptibility',
  historical_event_count_500m:    'Historical events (500m)',
};

export default function FeaturePanel({ features }) {
  // Animate bars in from 0 whenever features change
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    setAnimated(false);
    const t = requestAnimationFrame(() => {
      requestAnimationFrame(() => setAnimated(true));
    });
    return () => cancelAnimationFrame(t);
  }, [features]);

  if (!features || features.length === 0) {
    return (
      <div className="panel">
        <div className="panel-title">Feature Contributions</div>
        <div className="empty-state">Select a hex to view contributions</div>
      </div>
    );
  }

  const max = Math.max(...features.map((f) => Math.abs(f.contribution)), 0.01);

  return (
    <div className="panel">
      <div className="panel-title">Top Contributing Features</div>
      {features.map((f, i) => {
        const pct   = Math.round((Math.abs(f.contribution) / max) * 100);
        const label = FEATURE_LABELS[f.feature] || f.feature;
        return (
          <div key={i} className="feat-row">
            <div className="feat-name" title={f.feature}>{label}</div>
            <div className="feat-bar-wrap">
              <div
                className="feat-bar-fill"
                style={{
                  width: animated ? `${pct}%` : '0%',
                  transition: `width 0.55s cubic-bezier(0.4,0,0.2,1) ${i * 55}ms`,
                }}
              />
            </div>
            <div className="feat-val">{(f.contribution * 100).toFixed(0)}%</div>
          </div>
        );
      })}
    </div>
  );
}

