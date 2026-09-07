## Phase 12 — Frontend Dashboard

**Owner:** guru-elight · **SRS refs:** §7 (frozen stack), §12 (lead time), §13 (data-source banner), §15 (API contracts), §16 (sensor wording), §17 (alert dedup), §20 (demo escalation)

---

### Changes

| File | Purpose |
|------|---------|
| `frontend/vite.config.js` | Vite + React config; proxy `/api → localhost:8001` (stub) / `8000` (Phase 8) |
| `frontend/index.html` | Entry point |
| `frontend/src/main.jsx` | React root mount |
| `frontend/src/index.css` | Dark-theme design system, all CSS tokens |
| `frontend/src/api/client.js` | Axios wrapper for all §15 endpoints |
| `frontend/src/App.jsx` | Top-level layout; map polling every 10s; detail polling on hex selection |
| `frontend/src/components/HexMap.jsx` | Leaflet map (CLAUDE.md constraint) + h3-js hex polygons, tier colour-coded |
| `frontend/src/components/TrendLine.jsx` | Recharts line chart of `risk_score` history; §10.4 thresholds (30/55/75) |
| `frontend/src/components/ConfidenceLeadTime.jsx` | `confidence_score`, `lead_time_min`, `lead_time_basis` |
| `frontend/src/components/InundationView.jsx` | 2D inundation — **code-gated** at Orange/Red, returns `null` at Green/Yellow |
| `frontend/src/components/FeaturePanel.jsx` | Horizontal bar chart of `top_contributing_features` |
| `frontend/src/components/AlertFeed.jsx` | Polls every 10s; CAP alerts and downgrade events rendered as **distinct** types (§17) |
| `frontend/src/components/ValidationPanel.jsx` | Static LOEO results — fetches once on mount, no polling (§11) |
| `frontend/src/components/DataSourceLabel.jsx` | Always-visible banner: `"Data source: LIVE"` / `"Data source: CACHED DEMO"` (§13) |
| `frontend/src/components/SensorLabel.jsx` | `"external-data-only estimate"` when IoT offline — exact §16 wording, never "satellite-only" |
| `frontend/stub/server.cjs` | Express stub on port 8001; cycles 5 §20 escalation stages every 12s for offline dev |

---

### Stub demo flow (§20 stages, 12-second cycle)

| Stage | risk_score | tier | data_source | Event |
|-------|-----------|------|-------------|-------|
| Normal | 21 | Green | live | — |
| Rainfall rising | 48 | Yellow | live | — |
| Saturation | 67 | Orange | live | — |
| Slope response | 82 | Red | live | CAP alert fires |
| Decision | 82 | Red | cached_demo | DataSourceLabel flips |

---

### Build verification

```
npm install      ✓
npm run build    ✓  897 modules, exit 0
npm run stub     ✓  Express port 8001
npm run dev      ✓  Vite port 5173
```

---

### SRS §25 Phase 12 acceptance criteria

- [x] Leaflet map renders hex heatmap (not Mapbox — CLAUDE.md constraint)
- [x] Tier colours match §20 table (Green/Yellow/Orange/Red)
- [x] 1D trend line updates on polling — reference lines at §10.4 thresholds (30/55/75)
- [x] Inundation view **only** visible at Orange/Red — coded gate, not CSS
- [x] Feature-contribution panel renders top features
- [x] Confidence + lead time shows `no_red_crossing_in_forecast_window` when applicable
- [x] Validation panel is static (fetches once on mount, no re-polling)
- [x] Alert feed shows CAP alerts AND downgrade events as **distinct** item types
- [x] `"Data source: LIVE"` / `"Data source: CACHED DEMO"` always visible
- [x] `"external-data-only estimate"` shown for IoT-offline hex — never "satellite-only"

---

### Phase 8 integration note

When Guhan-10's Phase 8 FastAPI backend is ready, change **one line** in `vite.config.js`:

```js
// line 13 — swap these:
target: 'http://localhost:8001',   // ← stub (current)
// target: 'http://localhost:8000', // ← Phase 8 backend
```

No component changes required.

---

### CLAUDE.md constraints verified

- ✅ Leaflet only (no Mapbox)
- ✅ `antecedent_precipitation_index` — never `api_score`
- ✅ `"external-data-only estimate"` — never `"satellite-only"`
- ✅ `"soil saturation proxy"` wording in FeaturePanel labels
- ✅ Lead time: honest `no_red_crossing_in_forecast_window` string when no forecast crossing
- ✅ Schema and API contracts (§14, §15) not altered
