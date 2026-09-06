/**
 * TrendLine.jsx — Phase 12
 * 1D risk_score trend chart for selected hex.
 * SRS §15: data from GET /risk/{hex_id}/history
 */
import React from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';

// SRS §10.4 frozen tier boundaries: Yellow ≥ 30, Orange ≥ 55, Red ≥ 75
const TIER_THRESHOLDS = [
  { value: 30, tier: 'Yellow', color: '#eab308' },
  { value: 55, tier: 'Orange', color: '#f97316' },
  { value: 75, tier: 'Red',    color: '#ef4444' },
];

function formatTs(ts) {
  try {
    const d = new Date(ts);
    return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
  } catch { return ''; }
}

export default function TrendLine({ history }) {
  if (!history || history.length === 0) {
    return (
      <div className="panel">
        <div className="panel-title">Risk Score Trend</div>
        <div className="empty-state">Select a hex to view trend</div>
      </div>
    );
  }

  const data = history.map((row) => ({
    time: formatTs(row.timestamp),
    score: row.risk_score,
    tier: row.tier,
  }));

  return (
    <div className="panel">
      <div className="panel-title">Risk Score — 1D Trend</div>
      <ResponsiveContainer width="100%" height={110}>
        <LineChart data={data} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 9, fill: '#8b949e' }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 9, fill: '#8b949e' }}
            width={32}
          />
          <Tooltip
            contentStyle={{ background: '#21262d', border: '1px solid #30363d', fontSize: 11 }}
            labelStyle={{ color: '#8b949e' }}
          />
          {TIER_THRESHOLDS.map((t) => (
            <ReferenceLine
              key={t.tier}
              y={t.value}
              stroke={t.color}
              strokeDasharray="4 3"
              strokeOpacity={0.5}
              label={{ value: t.tier, position: 'insideTopLeft', fontSize: 8, fill: t.color }}
            />
          ))}
          <Line
            type="monotone"
            dataKey="score"
            stroke="#58a6ff"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#58a6ff' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
