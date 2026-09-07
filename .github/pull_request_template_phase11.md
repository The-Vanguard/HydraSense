## Phase 11 — CAP Alert Generation, Dedup & Downgrade

**Owner:** guru-elight · **SRS refs:** §14 (schema), §15 (API contracts), §17 (alert logic), §25 (acceptance)

---

### Summary

Implements the complete alert pipeline for HydraSense. When a hex crosses Orange or Red tier, `POST /alert/trigger` applies the SRS §17 dedup/downgrade rules, generates a valid CAP 1.2 XML alert, logs it to the `alerts` store, and fans out to a mock Sachet webhook and a simulated SMS log. `GET /alert/feed` returns the combined alert + downgrade event feed for the frontend.

Built as a standalone `backend/alerts/` package with a thread-safe in-memory store so it is fully testable without Phase 8's PostGIS database. When Guhan-10's Phase 8 backend lands, one `app.include_router(alerts_router)` call wires it in — no logic changes.

---

### Files

| File | Purpose |
|------|---------|
| `backend/alerts/models.py` | `AlertState`, `AlertRecord`, `DowngradeEvent` — pure-Python dataclasses mirroring SRS §14 schema |
| `backend/alerts/store.py` | Thread-safe in-memory store; same interface a SQLAlchemy/PostGIS layer would expose |
| `backend/alerts/cap_generator.py` | CAP 1.2 XML per §17.3; `<sent>` in IST (+05:30); `Severe` (Red) / `Moderate` (Orange) |
| `backend/alerts/dedup.py` | §17.1 dedup (fire if tier increased OR ≥30-min cooldown); §17.2 downgrade (2-cycle resolve) |
| `backend/alerts/fanout.py` | `[MOCK-SACHET]` webhook log → `data/alerts/sachet_webhook_log.jsonl`; `[MOCK-SMS]` → `data/alerts/sms_log.txt` |
| `backend/alerts/router.py` | `POST /alert/trigger` + `GET /alert/feed` (SRS §15) |
| `backend/alerts/app.py` | Standalone FastAPI app, port 8002. Guhan-10: `include_router(router)` to wire into Phase 8 |
| `backend/alerts/test_phase11.py` | 40 tests — all passing |
| `backend/requirements.txt` | `pydantic>=2.7.1` (relaxed from `==2.7.1` — no CPython 3.14 pre-built wheel exists for 2.7.1) |

---

### Dedup logic (SRS §17.1 & §17.2)

```
POST /alert/trigger receives {hex_id, tier, risk_score, confidence_score, lead_time_min, ...}

if last_alert_tier is None (first ever alert):
    → FIRE if tier in {Orange, Red}
    → SKIP  if tier in {Green, Yellow}  (no prior alert state to drop from)

if new_tier in {Orange, Red}:
    reset consecutive_below_orange_cycles = 0
    → FIRE if tier_rank(new_tier) > tier_rank(last_alert_tier) OR elapsed ≥ 30 min
    → SKIP otherwise  (cooldown window)

if new_tier in {Green, Yellow}:
    if last_alert_tier in {Orange, Red}:
        → DOWNGRADE: increment consecutive_below_orange_cycles
                     if cycles ≥ 2: emit "resolved" downgrade event
    else:
        → FIRE if new_tier > last_alert_tier (non-alert tier escalation, e.g. Green→Yellow)
        → SKIP otherwise
```

---

### CAP 1.2 XML structure (SRS §17.3)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>HYDRASENSE-WYD-2026-000001</identifier>
  <sender>hydrasense.sih2026@example.org</sender>
  <sent>2026-09-06T14:32:00+05:30</sent>  <!-- IST per §17.3 example -->
  <status>Actual</status>
  <msgType>Alert</msgType>
  <scope>Public</scope>
  <info>
    <category>Geo</category>
    <event>Flash Flood / Landslide Risk</event>
    <urgency>Immediate</urgency>
    <severity>Severe</severity>  <!-- Red=Severe, Orange=Moderate -->
    <certainty>Likely</certainty>
    <headline>High flash-flood/landslide risk: Mundakkai, Wayanad</headline>
    <description>Risk score 82/100 (RED), confidence 88/100. Estimated lead time:
    120 minutes (2h, forecast_crossing_t+2h, Open-Meteo). Nearest known shelter:
    Meppadi Government School (3.2 km, static lookup).</description>
    <area>
      <areaDesc>Mundakkai ward, Wayanad</areaDesc>
      <polygon>...H3 hex boundary coordinates...</polygon>
    </area>
  </info>
</alert>
```

---

### GET /alert/feed response (frontend rendering)

```json
[
  {
    "type": "cap",          ← rendered as urgent alert card
    "alert_id": "HYDRASENSE-WYD-2026-000001",
    "tier": "Red",
    "risk_score": 82,
    ...
  },
  {
    "type": "downgrade",    ← rendered as distinct, non-urgent entry
    "event_id": "DOWNGRADE-8860064e61fffff-1",
    "from_tier": "Red",
    "to_tier": "Yellow",
    "resolved": false,
    ...
  }
]
```

---

### Test results

```
python -m pytest backend/alerts/test_phase11.py -v

40 passed in 0.90s   (pytest 9.1.1, Python 3.14.3)
```

| Test group | Count | Covers |
|-----------|-------|--------|
| `TestCapXmlStructure` | 13 | §17.3 XML structure, identifier format, severity mapping, IST timestamp |
| `TestDedupFire` | 8 | First alert, tier increase, same-tier cooldown, cooldown expiry |
| `TestDedupDowngrade` | 8 | Tier drop, counter increment, 1-cycle not resolved, 2-cycle resolved, counter reset |
| `TestAlertFeedDistinctTypes` | 3 | `type:"cap"` vs `type:"downgrade"` in feed |
| `TestFanout` | 5 | Sachet log created, `[MOCK-SACHET]` label, SMS log created, `[MOCK-SMS]` label, channels returned |
| `TestTierOrdering` | 3 | Tier rank sanity |

---

### SRS §25 Phase 11 acceptance criteria

- [x] Red tier → well-formed CAP 1.2 XML, logged to `alerts`, visible via `GET /alert/feed`
- [x] Repeat Red within 30 min → no second alert (`action: "skipped"`)
- [x] Tier drop → `downgrade` event, **not** a new CAP alert
- [x] 2 consecutive below-Orange cycles → `"resolved": true` downgrade event
- [x] 1 consecutive below-Orange cycle → **not** resolved
- [x] Alert feed returns `type:"cap"` and `type:"downgrade"` as distinct items
- [x] Mock Sachet log labeled `[MOCK-SACHET]` (never a silent stub — CLAUDE.md)
- [x] Mock SMS log labeled `[MOCK-SMS]`
- [x] `lead_time_min` validated as multiple of 60 (SRS §12 hour-granular constraint)
- [x] All 40 tests passing

---

### Phase 8 integration (Guhan-10)

```python
# In your Phase 8 main app.py — one line:
from backend.alerts.router import router as alerts_router
app.include_router(alerts_router)

# Replace store.py with a SQLAlchemy/PostGIS implementation
# exposing the same interface:
#   get_state(), upsert_state(), next_alert_id(), append_alert(),
#   get_alerts(), next_downgrade_id(), append_downgrade(), get_feed()
```

---

### CLAUDE.md constraints verified

- ✅ Mock channels explicitly labeled — never a silent mock
- ✅ `antecedent_precipitation_index` — no mention of `api_score`
- ✅ No PSO-BP anywhere in this module
- ✅ `lead_time_min` validated as multiple of 60 (§12 constraint enforced in router)
- ✅ CAP `<sent>` in IST (+05:30) matching §17.3 frozen example
- ✅ Schema matches §14 exactly (no new fields added)
