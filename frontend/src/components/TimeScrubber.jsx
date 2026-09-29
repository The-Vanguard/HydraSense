/**
 * TimeScrubber.jsx — Historical + forecast time scrubber (Final.md §13.4)
 *
 * Allows dragging from -72h to the forecast window end (+6h by default).
 * Tier crossings are marked on the timeline.
 * "Live" position = 0 (current moment).
 */
import React, { useCallback } from 'react';

const HISTORY_H  = 72;
const FORECAST_H = 6;
const TOTAL_H    = HISTORY_H + FORECAST_H;

function hourLabel(offset) {
  if (offset === 0)  return 'LIVE';
  if (offset > 0)    return `+${offset}h`;
  return `${offset}h`;
}

export default function TimeScrubber({ offsetHours = 0, onChange, tierCrossings = [] }) {
  // Convert offset (-72..+6) to slider position (0..100)
  const pct = ((offsetHours + HISTORY_H) / TOTAL_H) * 100;

  const handleInput = useCallback(e => {
    const val = parseInt(e.target.value, 10);
    const offset = Math.round((val / 100) * TOTAL_H - HISTORY_H);
    onChange?.(offset);
  }, [onChange]);

  return (
    <div className="time-scrubber">
      <div className="scrubber-labels">
        <span className="scrubber-bound">-72h</span>
        <span className={`scrubber-live${offsetHours === 0 ? ' active' : ''}`}
              onClick={() => onChange?.(0)}>
          LIVE
        </span>
        <span className="scrubber-bound">+{FORECAST_H}h</span>
      </div>

      <div className="scrubber-track-wrap">
        {/* Tier-crossing markers */}
        {tierCrossings.map((tc, i) => {
          const pos = ((tc.offset + HISTORY_H) / TOTAL_H) * 100;
          return (
            <div
              key={i}
              className="scrubber-crossing"
              style={{ left: `${pos}%`, background: tc.color || '#ef4444' }}
              title={`${tc.tier} crossing at ${hourLabel(tc.offset)}`}
            />
          );
        })}

        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={Math.round(pct)}
          onChange={handleInput}
          className="scrubber-input"
        />
      </div>

      <div className="scrubber-current">
        {offsetHours === 0
          ? 'Showing live data'
          : offsetHours > 0
            ? `Forecast: +${offsetHours}h from now`
            : `Historical: ${Math.abs(offsetHours)}h ago`}
      </div>
    </div>
  );
}
