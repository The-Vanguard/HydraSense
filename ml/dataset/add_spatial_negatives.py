"""
ml/dataset/add_spatial_negatives.py -- Stage 4: training_table_v0 -> training_table_v1.

v0 negatives are all *temporal* (same place, other dates), so static terrain cannot separate them
from positives (univariate AUC of slope/elevation = 0.50 by construction).  v1 adds *spatial*
negatives (v2 Sec. 8.4): same prediction times as the event's positive rows, but at 3 other hilly
locations in the same region:
  * 8-35 km from the event; inside the region's plausibility box;
  * >= 10 km from EVERY recorded in-scope event location (unrecorded events near a storm are the
    main risk of a false negative, so the exclusion is deliberately generous);
  * "hilly": local slope >= 5 deg (so negatives are not trivially flat land).  Slope is NOT
    matched to the event's slope -- terrain must earn any signal it gets.
Rows carry neg_type = 'temporal' | 'spatial'; group = event_id (a spatial negative stays in its
event's CV fold).  Weight 0.5 like other negatives.
"""
import hashlib
import json
import math
import sys
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
OUT_PQ = ROOT / "data" / "events" / "training_table_v1.parquet"
OUT_CSV = ROOT / "data" / "events" / "training_table_v1.csv"
OUT_SUM = ROOT / "data" / "events" / "training_table_v1_summary.json"

N_SPATIAL = 3
N_CAND = 10
DIST_KM = (8.0, 35.0)
MIN_DIST_TO_ANY_EVENT_KM = 10.0
MIN_SLOPE_DEG = 5.0


def hav_km(a, b, c, d):
    p = math.radians
    x = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def main():
    v0 = pd.read_parquet(V0)
    ev = pd.read_csv(EV)
    ev_in = ev[ev["in_scope"] & ev["lat"].notna()]
    all_pts = list(zip(ev_in["lat"], ev_in["lon"]))
    ev_by_id = ev_in.set_index("event_id")
    out_rows, per_event = [], {}
    pos_all = v0[v0.label == 1]

    for eid, pos in pos_all.groupby("event_id"):
        r = ev_by_id.loc[eid]
        box = REGION_BOX[r["region"]]
        rng = np.random.default_rng(int(hashlib.md5(f"spatial|{eid}".encode()).hexdigest()[:8], 16))
        cands = []
        tries = 0
        while len(cands) < N_CAND and tries < 400:
            tries += 1
            d_km = rng.uniform(*DIST_KM)
            brg = rng.uniform(0, 2 * math.pi)
            la = r["lat"] + (d_km * math.cos(brg)) / 110.574
            lo = r["lon"] + (d_km * math.sin(brg)) / (111.320 * math.cos(math.radians(r["lat"])))
            if not (box[0] <= la <= box[1] and box[2] <= lo <= box[3]):
                continue
            if min(hav_km(la, lo, a, b) for a, b in all_pts) < MIN_DIST_TO_ANY_EVENT_KM:
                continue
            cands.append((la, lo))
        chosen = []
        for k, (la, lo) in enumerate(cands):
            terr = bt.fetch_terrain(f"{eid}_c{k}", la, lo)
            if terr["slope_deg"] == terr["slope_deg"] and terr["slope_deg"] >= MIN_SLOPE_DEG:
                chosen.append((k, la, lo, terr))
            if len(chosen) == N_SPATIAL:
                break
        t0, known = bt.onset(r)
        made = 0
        for k, la, lo, terr in chosen:
            raw = bt.fetch_rain(f"{eid}_s{k}", la, lo, t0)
            if not raw:
                continue
            s = bt.prep(raw)
            for _, p in pos.iterrows():
                t = datetime.fromisoformat(p["pred_time"])
                f = bt.features_at(s, t)
                if f is None:
                    continue
                base = {c: p[c] for c in ("event_id", "region", "hazard", "grade", "provenance",
                                          "severity", "time_uncertainty_h", "onset_known", "offset_h",
                                          "pred_time")}
                out_rows.append(dict(base, lat=la, lon=lo, geocode_status="SPATIAL_SAMPLE",
                                     position_uncertainty_m=100.0, terrain_reliable=True,
                                     hex_assignable=True, sample_id=f"{eid}|spat|{k}|{int(p['offset_h'])}",
                                     label=0, sample_weight=bt.NEG_WEIGHT, neg_type="spatial", **terr, **f))
                made += 1
        per_event[eid] = dict(candidates=len(cands), hilly_chosen=len(chosen), rows=made)
        print(f"{eid:26s} cand={len(cands):2d} hilly={len(chosen)} rows={made}")

    v0 = v0.copy()
    v0["neg_type"] = np.where(v0.label == 1, "positive", "temporal")
    v1 = pd.concat([v0, pd.DataFrame(out_rows)], ignore_index=True)
    bt.assert_no_simulated_in_features(v1)
    v1.to_parquet(OUT_PQ, index=False)
    v1.to_csv(OUT_CSV, index=False)
    summ = dict(rows=len(v1), by_type=v1.neg_type.value_counts().to_dict(),
                events_with_spatial=int(sum(1 for v in per_event.values() if v["rows"] > 0)),
                events_without_spatial=[k for k, v in per_event.items() if v["rows"] == 0],
                per_event=per_event)
    OUT_SUM.write_text(json.dumps(summ, indent=2))
    print(json.dumps({k: v for k, v in summ.items() if k != "per_event"}, indent=2))


if __name__ == "__main__":
    main()
