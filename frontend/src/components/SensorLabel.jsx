/**
 * SensorLabel.jsx — Phase 12
 * Shows "external-data-only estimate" when IoT sensor is offline.
 * SRS §16 frozen wording — never "satellite-only".
 */
import React from 'react';

export default function SensorLabel({ iotAnomalyFlag }) {
  if (!iotAnomalyFlag) return null;
  return (
    <div className="sensor-offline-label">
      ⚡ external-data-only estimate
    </div>
  );
}
