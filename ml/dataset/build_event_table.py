"""
ml/dataset/build_event_table.py -- Stage 4: event-centered training table (v0).

Input   data/events/historical_events_geocoded.csv   (all in-scope events, hazard + location)
Output  data/events/training_table_v0.parquet / .csv
        data/events/training_table_v0_summary.json

One row = one (event or negative, prediction time).  Every in-scope event is used; how much a row
is trusted is carried in `sample_weight`, `position_uncertainty_m` and `terrain_reliable`,
not by throwing events away.

Leakage rule (v2 Sec. 6.1, feature_timestamp <= prediction_timestamp):
  * t_onset_earliest = clock time from the notes column if one is given (minus time_uncertainty_h),
    otherwise 00:00 local on the event date.  Nothing later than this is ever assumed.
  * prediction time t = t_onset_earliest - offset_h.   Offsets: 72,48,24,12,6 always;
    3 and 1 only when a clock time was parsed (`onset_known`).  Rows are dropped when
    offset_h < time_uncertainty_h so a feature window can never overlap the real onset.
  * all rain/soil features use hours <= t.

Negatives (v2 Sec. 8.4): 5 per positive row, same location, drawn from the same-season window
[-60d,-14d] and [+14d,+45d] around the event; half are "hard" (7-day antecedent rain >= the 25th
percentile of that event's positive rows).  Weight 0.5 because the inventory is incomplete and
some negatives may be unrecorded events.

External calls (each has a timeout and a visible fallback: on failure the feature is NULL and the
row is flagged, never filled):  Open-Meteo Archive (hourly rain + soil moisture, ERA5-family
reanalysis, ~10-25 km grid) and Open-Meteo Elevation (Copernicus 90 m).
Known bias: reanalysis rain under-reads extreme convective events (data_limitations.md L1).
"""
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.provenance import assert_no_simulated_in_features  # noqa: E402

EV = ROOT / "data" / "events" / "historical_events_geocoded.csv"
OUT_PQ = ROOT / "data" / "events" / "training_table_v0.parquet"
OUT_CSV = ROOT / "data" / "events" / "training_table_v0.csv"
OUT_SUM = ROOT / "data" / "events" / "training_table_v0_summary.json"
CACHE = ROOT / "data" / "events" / "feature_cache"
CACHE.mkdir(exist_ok=True)

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
ELEV = "https://api.open-meteo.com/v1/elevation"
TIMEOUT = 40
OFFSETS = [72, 48, 24, 12, 6, 3, 1]
NEG_PER_POS = 5
NEG_WEIGHT = 0.5
LOOKBACK_DAYS = 80          # rain history fetched before onset (needs 15 d antecedent + 60 d negatives)
LOOKAHEAD_DAYS = 46
HDR = {"User-Agent": "HydraSense-SIH26192-dataset/1.0"}


# ---------------------------------------------------------------- event time
CLOCK = re.compile(r"~?\b([01]?\d|2[0-3]):([0-5]\d)\b")


def onset(row):
    """Return (t_onset_earliest, onset_known)."""
    d = datetime.strptime(row["date"], "%d-%m-%Y")
    m = CLOCK.search(str(row.get("notes", "")))
    if m and row["time_uncertainty_h"] <= 6:
        t = d.replace(hour=int(m.group(1)), minute=int(m.group(2)))
        return t - timedelta(hours=float(row["time_uncertainty_h"])), True
    return d, False                                   # 00:00 local: earliest plausible onset


# ---------------------------------------------------------------- fetch helpers
_LAST_CALL = {}
# Open-Meteo counts every coordinate as a call (~600/min).  A 25-coordinate elevation request
# therefore needs >= 2.5 s spacing; archive requests are cheaper.
_MIN_INTERVAL_S = {ELEV: 2.8, ARCHIVE: 1.0}


def get_json(url, params, tries=4):
    """Paced GET with backoff on 429/5xx/timeouts.  Raises after the last try (caller labels NULL)."""
    last = None
    for k in range(tries):
        wait = _MIN_INTERVAL_S.get(url, 0.5) - (time.time() - _LAST_CALL.get(url, 0.0))
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[url] = time.time()
        try:
            r = requests.get(url, params=params, headers=HDR, timeout=TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
            time.sleep(20 * (k + 1))          # minute-window limit: wait for it to reset
    raise last


def cached_json(path, fetch):
    if path.exists():
        return json.loads(path.read_text())
    try:
        out = fetch()
    except Exception as exc:                          # visible fallback: NULL features
        print(f"   ! fetch failed ({path.name}): {exc}", file=sys.stderr)
        return None
    path.write_text(json.dumps(out))
    return out


def fetch_rain(ev_id, lat, lon, t0):
    def go():
        s = (t0 - timedelta(days=LOOKBACK_DAYS)).date()
        e = min((t0 + timedelta(days=LOOKAHEAD_DAYS)).date(), (datetime.now() - timedelta(days=6)).date())
        return get_json(ARCHIVE, {
            "latitude": lat, "longitude": lon, "start_date": s.isoformat(), "end_date": e.isoformat(),
            "hourly": "precipitation,soil_moisture_0_to_7cm,soil_moisture_7_to_28cm",
            "timezone": "Asia/Kolkata"})
    return cached_json(CACHE / f"rain_{ev_id}.json", go)


def fetch_terrain(ev_id, lat, lon):
    """5x5 grid, 0.001 deg (~110 m) spacing.  slope from central 3x3 (Horn), relief over 5x5."""
    def go():
        offs = [-2, -1, 0, 1, 2]
        la = [lat + i * 0.001 for i in offs for _ in offs]
        lo = [lon + j * 0.001 for _ in offs for j in offs]
        j = get_json(ELEV, {"latitude": ",".join(f"{x:.5f}" for x in la),
                            "longitude": ",".join(f"{x:.5f}" for x in lo)})
        return {"elev": j["elevation"], "lat": lat}
    j = cached_json(CACHE / f"terr_{ev_id}.json", go)
    if not j:
        return dict(elevation_m=np.nan, slope_deg=np.nan, relief_m_440=np.nan)
    z = np.array(j["elev"], dtype=float).reshape(5, 5)
    dx = 0.001 * 111_320 * math.cos(math.radians(lat))
    dy = 0.001 * 110_574
    c = z[1:4, 1:4]                                   # Horn 3x3 on central cells
    dzdx = ((c[0, 2] + 2 * c[1, 2] + c[2, 2]) - (c[0, 0] + 2 * c[1, 0] + c[2, 0])) / (8 * dx)
    dzdy = ((c[2, 0] + 2 * c[2, 1] + c[2, 2]) - (c[0, 0] + 2 * c[0, 1] + c[0, 2])) / (8 * dy)
    return dict(elevation_m=float(z[2, 2]),
                slope_deg=float(math.degrees(math.atan(math.hypot(dzdx, dzdy)))),
                relief_m_440=float(z.max() - z.min()))


# ---------------------------------------------------------------- features at time t
def features_at(series, t):
    """series: dict with 'time' (ISO local), 'precipitation', soil moisture lists."""
    times = series["_times"]
    i = series["_index"].get(t.strftime("%Y-%m-%dT%H:00"))
    if i is None:
        return None
    p = series["_p"]

    def ssum(h):
        lo = i - h + 1
        return float(np.nansum(p[lo:i + 1])) if lo >= 0 else np.nan
    if i - 15 * 24 + 1 < 0:
        return None
    f = dict(rain_1h=ssum(1), rain_3h=ssum(3), rain_6h=ssum(6), rain_12h=ssum(12), rain_24h=ssum(24),
             antecedent_rain_3d=ssum(72), antecedent_rain_7d=ssum(168), antecedent_rain_15d=ssum(360),
             rain_max_1h_6h=float(np.nanmax(p[i - 5:i + 1])),
             soil_moisture_0_7=series["_s1"][i], soil_moisture_7_28=series["_s2"][i])
    return f


def prep(series):
    times = series["hourly"]["time"]
    return dict(_times=times, _index={t: k for k, t in enumerate(times)},
                _p=np.array(series["hourly"]["precipitation"], dtype=float),
                _s1=np.array(series["hourly"]["soil_moisture_0_to_7cm"], dtype=float),
                _s2=np.array(series["hourly"]["soil_moisture_7_to_28cm"], dtype=float))


def location_weight(unc_m):
    return float(np.clip(10_000 / max(unc_m, 10_000), 0.2, 1.0))


# ---------------------------------------------------------------- main
def main():
    ev = pd.read_csv(EV)
    ev = ev[ev["in_scope"] & ev["lat"].notna()].copy()
    rows, skipped = [], []
    for _, r in ev.iterrows():
        eid = r["event_id"]
        t0, known = onset(r)
        raw = fetch_rain(eid, r["lat"], r["lon"], t0)
        if not raw:
            skipped.append((eid, "rain fetch failed"))
            continue
        s = prep(raw)
        terr = fetch_terrain(eid, r["lat"], r["lon"])
        unc = float(r["position_uncertainty_m_final"])
        base = dict(event_id=eid, region=r["region"], hazard=r["type"], grade=r["grade"],
                    provenance=r["provenance"], severity=r["severity"], lat=r["lat"], lon=r["lon"],
                    geocode_status=r["geocode_status"], position_uncertainty_m=unc,
                    time_uncertainty_h=float(r["time_uncertainty_h"]), onset_known=known,
                    terrain_reliable=bool(unc <= 3000 and terr["slope_deg"] == terr["slope_deg"]),
                    hex_assignable=bool(r["hex_assignable"]), **terr)
        pos = []
        for off in OFFSETS:
            if off < r["time_uncertainty_h"]:
                continue                                  # would overlap the real onset
            if off in (1, 3) and not known:
                continue                                  # no clock time: sub-6h offsets are meaningless
            t = t0 - timedelta(hours=off)
            f = features_at(s, t)
            if f is None:
                continue
            pos.append(dict(base, sample_id=f"{eid}|pos|{off}", label=1, offset_h=off,
                            pred_time=t.isoformat(), sample_weight=location_weight(unc), **f))
        if not pos:
            skipped.append((eid, "no usable offsets"))
            continue
        rows += pos
        # ---- negatives
        rng = np.random.default_rng(int(hashlib.md5(eid.encode()).hexdigest()[:8], 16))
        grid = []
        for lo_d, hi_d in ((-60, -14), (14, 45)):
            t = t0 + timedelta(days=lo_d)
            while t <= t0 + timedelta(days=hi_d):
                grid.append(t.replace(minute=0, second=0, microsecond=0))
                t += timedelta(hours=12)
        cand = [(t, features_at(s, t)) for t in grid]
        cand = [(t, f) for t, f in cand if f is not None and f["rain_1h"] == f["rain_1h"]]
        if not cand:
            continue
        thr = np.percentile([p["antecedent_rain_7d"] for p in pos], 25)
        hard = [c for c in cand if c[1]["antecedent_rain_7d"] >= thr]
        n_neg = NEG_PER_POS * len(pos)
        n_hard = min(len(hard), n_neg // 2)
        pick = []
        if n_hard:
            pick += [hard[k] for k in rng.choice(len(hard), n_hard, replace=False)]
        rest = [c for c in cand if c not in pick]
        n_rest = min(len(rest), n_neg - len(pick))
        pick += [rest[k] for k in rng.choice(len(rest), n_rest, replace=False)]
        for k, (t, f) in enumerate(pick):
            rows.append(dict(base, sample_id=f"{eid}|neg|{k}", label=0, offset_h=np.nan,
                             pred_time=t.isoformat(), sample_weight=NEG_WEIGHT, **f))
        print(f"{eid:26s} pos={len(pos)} neg={len(pick)} onset_known={known}")
    df = pd.DataFrame(rows)
    assert_no_simulated_in_features(df)
    df.to_parquet(OUT_PQ, index=False)
    df.to_csv(OUT_CSV, index=False)
    pos, neg = df[df.label == 1], df[df.label == 0]
    summ = dict(
        rows=len(df), positives=len(pos), negatives=len(neg),
        events_used=int(pos.event_id.nunique()), events_skipped=skipped,
        events_by_hazard=pos.groupby("hazard").event_id.nunique().to_dict(),
        events_by_region=pos.groupby("region").event_id.nunique().to_dict(),
        events_terrain_reliable=int(pos.drop_duplicates("event_id").terrain_reliable.sum()),
        events_onset_known=int(pos.drop_duplicates("event_id").onset_known.sum()),
        null_pct={c: round(float(df[c].isna().mean() * 100), 1) for c in df.columns
                  if c.startswith(("rain", "antecedent", "soil", "slope", "elev", "relief"))},
        v2_features_present=["elevation_m", "slope_deg", "relief_m_440(proxy)", "rain_1h", "rain_3h",
                             "rain_6h", "rain_12h", "rain_24h", "antecedent_rain_3d/7d/15d"],
        v2_features_missing="aspect, curvature, twi, hand_m, soil texture/depth, land cover, "
                            "distance_to_stream/road, gsi_*, historical_event_count, r_int, p_fs_lt1, "
                            "scs_runoff_mm, tc_min, catchment_area_km2, iot_soil_moisture -- need the "
                            "onboarding pipeline / engines per event location (next step)",
    )
    OUT_SUM.write_text(json.dumps(summ, indent=2, default=str))
    print(json.dumps(summ, indent=2, default=str))


if __name__ == "__main__":
    main()
