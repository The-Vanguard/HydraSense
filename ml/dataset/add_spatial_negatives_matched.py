"""
ml/dataset/add_spatial_negatives_matched.py -- training_table_v0 -> training_table_v1b.

Fixes the two problems found in v1 (random hilly points):
  1. 23/52 events got no spatial negatives because elevation fetches failed under rate limits.
     -> fetches now retry with backoff (build_event_table.get_json); cached points are reused.
  2. Terrain AUC came out *inverted* (slope 0.32): recorded events sit at named places, near roads
     and people, in gentler/lower terrain than random hills.  Reporting bias, not physics.
     -> spatial negatives are drawn from OpenStreetMap named places (village/hamlet/town/suburb),
        the same kind of location the events were geocoded to.

Selection per event (seeded): OSM place nodes 8-35 km from the event, inside the region's box,
>= 10 km from every recorded in-scope event, local slope >= 5 deg; 3 kept.  They are scored at
the SAME prediction times as the event's positive rows.

Rows: neg_type='spatial_place', label_basis='assumed_no_event_spatial'.  Existing v0 rows get
label_basis 'recorded_event' / 'assumed_no_event_temporal'.  Provenance tag is unchanged
(inherited) -- see the note in the run summary; label_basis is the honest marker.
"""
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_event_table as bt          # noqa: E402
from geocode_events import REGION_BOX   # noqa: E402

V0 = ROOT / "data" / "events" / "training_table_v0.parquet"
EV = ROOT / "data" / "events" / "historical_events_geocoded.csv"
OUT_PQ = ROOT / "data" / "events" / "training_table_v1b.parquet"
OUT_CSV = ROOT / "data" / "events" / "training_table_v1b.csv"
OUT_SUM = ROOT / "data" / "events" / "training_table_v1b_summary.json"

OVERPASS = "https://overpass-api.de/api/interpreter"
N_SPATIAL, N_CAND = 3, 8
DIST_KM = (8.0, 35.0)
MIN_DIST_TO_ANY_EVENT_KM = 10.0
MIN_SLOPE_DEG = 5.0


def hav_km(a, b, c, d):
    p = math.radians
    x = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def place_nodes(eid, lat, lon):
    """Named place nodes within 36 km of the event (cached; NULL list on failure, never invented)."""
    path = bt.CACHE / f"places_{eid}.json"
    q = ('[out:json][timeout:90];node["place"~"^(village|hamlet|town|suburb)$"]["name"]'
         f'(around:36000,{lat},{lon});out;')

    def go():
        time.sleep(2.0)
        last = None
        for k in range(4):
            try:
                import requests
                r = requests.post(OVERPASS, data={"data": q}, headers=bt.HDR, timeout=120)
                if r.status_code in (429, 504):
                    raise RuntimeError(f"Overpass HTTP {r.status_code}")
                r.raise_for_status()
                return [(e["lat"], e["lon"], e["tags"].get("name", "")) for e in r.json()["elements"]]
            except Exception as exc:
                last = exc
                time.sleep(8 * (k + 1))
        raise last
    return bt.cached_json(path, go) or []


def main():
    v0 = pd.read_parquet(V0)
    ev = pd.read_csv(EV)
    ev_in = ev[ev["in_scope"] & ev["lat"].notna()]
    all_pts = list(zip(ev_in["lat"], ev_in["lon"]))
    ev_by_id = ev_in.set_index("event_id")
    out_rows, per_event = [], {}

    for eid, pos in v0[v0.label == 1].groupby("event_id"):
        r = ev_by_id.loc[eid]
        box = REGION_BOX[r["region"]]
        rng = np.random.default_rng(int(hashlib.md5(f"place|{eid}".encode()).hexdigest()[:8], 16))
        nodes = place_nodes(eid, r["lat"], r["lon"])
        ok = []
        for la, lo, name in nodes:
            d = hav_km(r["lat"], r["lon"], la, lo)
            if not (DIST_KM[0] <= d <= DIST_KM[1]):
                continue
            if not (box[0] <= la <= box[1] and box[2] <= lo <= box[3]):
                continue
            if min(hav_km(la, lo, a, b) for a, b in all_pts) < MIN_DIST_TO_ANY_EVENT_KM:
                continue
            ok.append((la, lo, name))
        order = rng.permutation(len(ok))[:N_CAND]
        chosen = []
        for k in order:
            la, lo, name = ok[k]
            terr = bt.fetch_terrain(f"{eid}_p{k}", la, lo)
            if terr["slope_deg"] == terr["slope_deg"] and terr["slope_deg"] >= MIN_SLOPE_DEG:
                chosen.append((k, la, lo, name, terr))
            if len(chosen) == N_SPATIAL:
                break
        t0, _ = bt.onset(r)
        made = 0
        for k, la, lo, name, terr in chosen:
            raw = bt.fetch_rain(f"{eid}_q{k}", la, lo, t0)
            if not raw:
                continue
            s = bt.prep(raw)
            for _, p in pos.iterrows():
                f = bt.features_at(s, datetime.fromisoformat(p["pred_time"]))
                if f is None:
                    continue
                base = {c: p[c] for c in ("event_id", "region", "hazard", "grade", "provenance",
                                          "severity", "time_uncertainty_h", "onset_known", "offset_h",
                                          "pred_time")}
                out_rows.append(dict(base, lat=la, lon=lo, geocode_status="SPATIAL_PLACE",
                                     place_name=name, position_uncertainty_m=300.0,
                                     terrain_reliable=True, hex_assignable=True,
                                     sample_id=f"{eid}|plc|{k}|{int(p['offset_h'])}", label=0,
                                     sample_weight=bt.NEG_WEIGHT, neg_type="spatial_place",
                                     label_basis="assumed_no_event_spatial", **terr, **f))
                made += 1
        per_event[eid] = dict(place_nodes=len(nodes), eligible=len(ok), chosen=len(chosen), rows=made)
        print(f"{eid:26s} nodes={len(nodes):4d} eligible={len(ok):4d} chosen={len(chosen)} rows={made}",
              flush=True)

    v0 = v0.copy()
    v0["neg_type"] = np.where(v0.label == 1, "positive", "temporal")
    v0["label_basis"] = np.where(v0.label == 1, "recorded_event", "assumed_no_event_temporal")
    v1b = pd.concat([v0, pd.DataFrame(out_rows)], ignore_index=True)
    bt.assert_no_simulated_in_features(v1b)
    v1b.to_parquet(OUT_PQ, index=False)
    v1b.to_csv(OUT_CSV, index=False)
    summ = dict(rows=len(v1b), by_type=v1b.neg_type.value_counts().to_dict(),
                events_with_spatial=int(sum(1 for v in per_event.values() if v["rows"] > 0)),
                events_without_spatial=[k for k, v in per_event.items() if v["rows"] == 0],
                per_event=per_event)
    OUT_SUM.write_text(json.dumps(summ, indent=2))
    print(json.dumps({k: v for k, v in summ.items() if k != "per_event"}, indent=2))


if __name__ == "__main__":
    main()
