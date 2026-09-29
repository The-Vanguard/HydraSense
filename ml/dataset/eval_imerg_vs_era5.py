"""
ml/dataset/eval_imerg_vs_era5.py -- does satellite rain (GPM IMERG Final, daily) beat reanalysis rain?

Same rows as training_table_v0p; same leave-one-event-out validation.  Both sources are reduced to
the SAME leak-free daily features, so the comparison is fair:

  x_1d   rain on the last COMPLETE UTC day before the prediction time
  x_3d / x_7d / x_15d   sum over the last 3 / 7 / 15 complete UTC days

Why complete days only: a daily total for the day that contains the prediction time includes rain
that falls AFTER the prediction (near onset, that is the triggering storm).  Using only days that
ended before the prediction keeps feature_timestamp <= prediction_timestamp (v2 Sec. 6.1), at the
cost of ignoring up to 24 h of the most recent rain.  Local (IST) times are converted to UTC.

  ERA5   : hourly Open-Meteo reanalysis already cached per event (feature_cache/rain_<event>.json)
  IMERG  : data/events/imerg_daily_cache.jsonl from fetch_imerg_daily.py (mm/day, 0.1 deg cell)
Rows without IMERG (pre-2000 event, missing days) are dropped from BOTH sides for the comparison.

Writes data/validation/imerg_vs_era5_results.json.  Not a claim of operational skill.
"""
import json
import sys
import warnings
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import train_baseline_v0 as base  # noqa: E402

ROOT = base.ROOT
TABLE = ROOT / "data" / "events" / "training_table_v0p.parquet"
CACHE = ROOT / "data" / "events" / "imerg_daily_cache.jsonl"
FEAT = ROOT / "data" / "events" / "feature_cache"
OUT = ROOT / "data" / "validation" / "imerg_vs_era5_results.json"
WINDOWS = {"1d": 1, "3d": 3, "7d": 7, "15d": 15}


def load_imerg():
    d = {}
    for line in CACHE.read_text().splitlines():
        o = json.loads(line)
        xi, yi, day = o["k"].split(",")
        d[(int(xi), int(yi), day)] = o["v"]
    return d


_era_cache = {}


def era5_daily(event_id):
    """UTC-day totals (mm) from the cached hourly reanalysis; days with < 24 hours are NaN."""
    if event_id not in _era_cache:
        j = json.loads((FEAT / f"rain_{event_id}.json").read_text())
        t = pd.to_datetime(j["hourly"]["time"]) - pd.Timedelta(hours=5.5)      # local -> UTC
        s = pd.Series(np.array(j["hourly"]["precipitation"], dtype=float), index=t)
        g = s.groupby(s.index.normalize())
        tot = g.sum(min_count=24)
        tot[g.count() < 24] = np.nan
        _era_cache[event_id] = tot
    return _era_cache[event_id]


def add_features(df, imerg):
    era, sat = {k: [] for k in WINDOWS}, {k: [] for k in WINDOWS}
    for r in df.itertuples():
        t_u = pd.Timestamp(r.pred_time) - timedelta(hours=5.5)
        last = t_u.normalize() - timedelta(days=1)                    # last complete UTC day
        xi, yi = int((r.lon + 180) / 0.1), int((r.lat + 90) / 0.1)
        e_series = era5_daily(r.event_id)
        for name, n in WINDOWS.items():
            days = [last - timedelta(days=k) for k in range(n)]
            ev = [e_series.get(d, np.nan) for d in days]
            sv = [imerg.get((xi, yi, d.strftime("%Y%m%d")), np.nan) for d in days]
            sv = [np.nan if v is None else v for v in sv]
            era[name].append(np.nan if np.isnan(ev).any() else float(np.sum(ev)))
            sat[name].append(np.nan if np.isnan(sv).any() else float(np.sum(sv)))
    out = df.copy()
    for k in WINDOWS:
        out[f"era5_{k}"], out[f"imerg_{k}"] = era[k], sat[k]
    return out


def auc(d, c):
    ok = d[c].notna()
    return round(float(roc_auc_score(d.loc[ok, "label"], d.loc[ok, c])), 3) if d.loc[ok, "label"].nunique() > 1 else None


def head(d, hazard):
    h = d[d.hazard == hazard].copy()
    res = dict(hazard=hazard, events=int(h[h.label == 1].event_id.nunique()), rows=len(h))
    for src in ("era5", "imerg"):
        res[f"{src}_single_feature_auc"] = {k: auc(h, f"{src}_{k}") for k in WINDOWS}
    sets = {"era5_daily": [f"era5_{k}" for k in WINDOWS], "imerg_daily": [f"imerg_{k}" for k in WINDOWS],
            "both": [f"era5_{k}" for k in WINDOWS] + [f"imerg_{k}" for k in WINDOWS]}
    for name, cols in sets.items():
        for kind in ("logit", "xgb"):
            y, p = base.loo(h, "event_id", kind, cols)
            res[f"{kind}_loeo_{name}"] = base.metrics(y.label, p)
    y, p = base.loo(h, "event_id", "xgb", sets["imerg_daily"], shuffle=True, seed=7)
    res["control_shuffled_imerg_xgb_auc"] = base.metrics(y.label, p)["auc"]
    pos = h[(h.label == 1) & h.imerg_1d.notna() & h.era5_1d.notna() & (h.offset_h <= 24)]
    ratio = (pos.imerg_1d + 0.1) / (pos.era5_1d + 0.1)
    res["imerg_over_era5_1d_before_onset_median"] = round(float(ratio.median()), 2) if len(pos) else None
    return res


def main():
    df = pd.read_parquet(TABLE)
    df["event_id"] = df["event_id"].astype(str)
    df = add_features(df, load_imerg())
    keep = df[[f"imerg_{k}" for k in WINDOWS] + [f"era5_{k}" for k in WINDOWS]].notna().all(axis=1)
    dropped = sorted(df.loc[~keep, "event_id"].unique())
    d = df[keep].copy()
    # keep only events that still have both classes
    ok_ev = d.groupby("event_id").label.nunique()
    d = d[d.event_id.isin(ok_ev[ok_ev == 2].index)]
    out = dict(rows_used=len(d), rows_dropped=int((~keep).sum()), events_with_dropped_rows=dropped,
               note="features use complete UTC days before the prediction time only",
               heads=[head(d, h) for h in ("landslide", "flash_flood")])
    OUT.write_text(json.dumps(out, indent=2))
    for h in out["heads"]:
        print(f"\n=== {h['hazard']}: {h['events']} events, {h['rows']} rows")
        print("  single-feature AUC  ERA5 :", h["era5_single_feature_auc"])
        print("  single-feature AUC  IMERG:", h["imerg_single_feature_auc"])
        for k in ("logit_loeo_era5_daily", "logit_loeo_imerg_daily", "logit_loeo_both",
                  "xgb_loeo_era5_daily", "xgb_loeo_imerg_daily", "xgb_loeo_both"):
            m = h[k]
            print(f"  {k:26s} AUC={m['auc']}  PR-AUC={m['pr_auc']}  Brier={m['brier']}")
        print("  control (shuffled labels, IMERG xgb) AUC =", h["control_shuffled_imerg_xgb_auc"])
        print("  median IMERG/ERA5 rain on the last full day before onset:", h["imerg_over_era5_1d_before_onset_median"])
    print(f"\nrows used {out['rows_used']}, dropped {out['rows_dropped']} (events: {dropped})")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
