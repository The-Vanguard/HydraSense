"""
ml/dataset/train_baseline_v0p.py -- baseline v0 + v2 physics features (option 1).

Same table, same leave-one-event-out validation as train_baseline_v0.py, with three additions:
  sat_m / p_fs_lt1 / fs_p50   infinite-slope physics (generic soil parameters, flagged)
  r_int_caine                 published global I-D threshold ratio (no fitting)
  r_int_fit                   I-D threshold FITTED INSIDE EACH FOLD on training positives only

Feature sets compared (XGBoost, LOEO):
  dyn                 rain / soil moisture only            (the v0 result)
  dyn+phys            dyn + sat_m + p_fs_lt1 + r_int_*
  phys                sat_m, p_fs_lt1, r_int_caine, r_int_fit only
Baselines: r_int_caine alone (no fitting), p_fs_lt1 alone, logistic regression on r_int_* + p_fs_lt1.
Control: shuffled labels within events.

Writes data/validation/baseline_v0p_results.json (new file).
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import physics_features as pf                       # noqa: E402
import train_baseline_v0 as base                    # noqa: E402

ROOT = base.ROOT
OUT = ROOT / "data" / "validation" / "baseline_v0p_results.json"
OUT_TABLE = ROOT / "data" / "events" / "training_table_v0p.parquet"

PHYS = ["sat_m", "p_fs_lt1", "r_int_caine", "r_int_fit"]


def with_fold_rint(tr, te):
    a, b = pf.fit_id_threshold(tr)
    tr, te = tr.copy(), te.copy()
    tr["r_int_fit"], te["r_int_fit"] = pf.rint_fit(tr, a, b), pf.rint_fit(te, a, b)
    return tr, te


def loo_prep(df, kind, cols, shuffle=False, seed=base.SEED):
    """Leave-one-event-out with the I-D threshold refitted on each training fold."""
    rng = np.random.default_rng(seed)
    d = df.reset_index(drop=True).copy()
    if shuffle:
        d["label"] = d.groupby("event_id")["label"].transform(lambda s: rng.permutation(s.to_numpy()))
    pred = np.full(len(d), np.nan)
    for g in d["event_id"].unique():
        te_m = d["event_id"] == g
        tr, te = d[~te_m], d[te_m]
        if tr.label.nunique() < 2:
            continue
        tr, te = with_fold_rint(tr, te)
        pred[te_m.to_numpy()] = base.fit_predict(kind, tr, te, cols)
    ok = ~np.isnan(pred)
    return d[ok], pred[ok]


def auc_alone(d, col):
    x = d[col].fillna(d[col].median()).to_numpy(float)
    return round(float(roc_auc_score(d["label"], x)), 3)


def run_head(df, hazard):
    d = df[df.hazard == hazard].copy()
    n_ev = int(d[d.label == 1].event_id.nunique())
    res = dict(hazard=hazard, events=n_ev, rows=len(d), note="illustrative: very few events" if n_ev < 20 else "")
    sets = {"xgb_dyn": base.DYN, "xgb_dyn_plus_phys": base.DYN + PHYS, "xgb_phys_only": PHYS}
    for name, cols in sets.items():
        y, p = loo_prep(d, "xgb", cols)
        res[name] = base.metrics(y.label, p)
    y, p = loo_prep(d, "logit", ["r_int_caine", "r_int_fit", "p_fs_lt1"])
    res["logit_phys_baseline"] = base.metrics(y.label, p)
    res["r_int_caine_alone_auc"] = auc_alone(d, "r_int_caine")
    res["p_fs_lt1_alone_auc"] = auc_alone(d, "p_fs_lt1")
    res["rain_24h_alone_auc"] = auc_alone(d, "rain_24h")
    res["control_shuffled_labels_auc"] = [base.metrics(*(lambda y, p: (y.label, p))(
        *loo_prep(d, "xgb", base.DYN + PHYS, shuffle=True, seed=100 + s)))["auc"] for s in range(3)]
    # fitted threshold on ALL events, descriptive only (the honest per-fold fits are used above)
    a, b = pf.fit_id_threshold(d)
    res["id_threshold_full_fit_descriptive"] = dict(alpha=round(a, 2), beta=round(b, 3),
                                                     caine=dict(alpha=14.82, beta=0.39))
    m = base.xgb().fit(pf_fill(d)[base.DYN + PHYS].to_numpy(float), d["label"], sample_weight=d["sample_weight"])
    imp = sorted(zip(base.DYN + PHYS, m.feature_importances_), key=lambda t: -t[1])[:6]
    res["top_features_full_fit_descriptive"] = [(k, round(float(v), 3)) for k, v in imp]
    return res


def pf_fill(d):
    d = d.copy()
    a, b = pf.fit_id_threshold(d)
    d["r_int_fit"] = pf.rint_fit(d, a, b)
    return d


def main():
    df = pd.read_parquet(base.TABLE)
    df["event_id"] = df["event_id"].astype(str)
    df = pf.add_static_physics(df)
    df.to_parquet(OUT_TABLE, index=False)
    out = dict(table=str(OUT_TABLE.relative_to(ROOT)),
               validation="leave-one-event-out; I-D threshold refitted inside every training fold",
               physics_constants=dict(theta_r=pf.THETA_R, theta_sat=pf.THETA_SAT, soil=pf.GENERIC_SOIL,
                                      fs_param_source=pf.FS_PARAM_SOURCE),
               caveats=["FS uses GENERIC soil parameters and a default depth, not local measurements",
                        "theta_r / theta_sat are provisional; slope from a 90 m DEM (unreliable when "
                        "position uncertainty > 3 km)",
                        "small table; reanalysis rain under-reads extreme events"],
               heads=[run_head(df, h) for h in ("landslide", "flash_flood")])
    OUT.write_text(json.dumps(out, indent=2))
    for h in out["heads"]:
        print(f"\n=== {h['hazard']}: {h['events']} events, {h['rows']} rows ({h['note']})")
        for k in ("xgb_dyn", "xgb_dyn_plus_phys", "xgb_phys_only", "logit_phys_baseline"):
            print(f"  {k:22s} {h[k]}")
        print(f"  alone (no fitting): r_int_caine={h['r_int_caine_alone_auc']}  p_fs_lt1={h['p_fs_lt1_alone_auc']}  rain_24h={h['rain_24h_alone_auc']}")
        print(f"  CONTROL shuffled-label AUC = {h['control_shuffled_labels_auc']}")
        print(f"  I-D threshold (all-event fit, descriptive): {h['id_threshold_full_fit_descriptive']}")
        print(f"  top features (descriptive): {h['top_features_full_fit_descriptive']}")
    print(f"\nwrote {OUT.relative_to(ROOT)} and {OUT_TABLE.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
