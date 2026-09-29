"""
ml/dataset/train_baseline_v0.py -- first honest baseline on training_table_v0.

  * One XGBoost classifier per hazard head (v2 Sec. 8.2): landslide (hex x time) and flash flood.
    NOTE: the flood head here is trained on 13 point events, not micro-catchments -- illustrative.
  * Validation: leave-one-event-out (LOEO): every row of an event (all offsets + its negatives) is
    held out together.  Leave-one-region-out (LORO) is also run, per held-out region, with event
    counts, and labelled illustrative because no region has >= 15 events per hazard (v2 Sec. 15.3).
  * Features: dynamic rain / soil-moisture only.  v0 negatives are temporal (same place), so static
    terrain cannot help by construction; an ablation with terrain is reported to show that.
  * Baselines: (a) 24 h rain alone, (b) logistic regression on rain + antecedent rain.
  * Control: the same LOEO pipeline with labels shuffled within each event -> AUC should be ~0.5.
  * Metrics: ROC-AUC, PR-AUC (base rate shown), Brier.  Accuracy is not used (class imbalance).

Writes data/validation/baseline_v0_results.json (new file; existing frozen validation files untouched).
Nothing here is a claim of operational skill: the table is small, reanalysis rain under-reads
extreme events (docs/data_limitations.md L1), and negatives may hide unrecorded events.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "data" / "events" / "training_table_v0.parquet"
OUT = ROOT / "data" / "validation" / "baseline_v0_results.json"

DYN = ["rain_1h", "rain_3h", "rain_6h", "rain_12h", "rain_24h", "rain_max_1h_6h",
       "antecedent_rain_3d", "antecedent_rain_7d", "antecedent_rain_15d",
       "soil_moisture_0_7", "soil_moisture_7_28"]
STATIC = ["elevation_m", "slope_deg", "relief_m_440"]
LOGIT = ["rain_24h", "antecedent_rain_3d", "antecedent_rain_7d", "antecedent_rain_15d"]
SEED = 42


def xgb():
    return XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8,
                         colsample_bytree=0.8, min_child_weight=3, reg_lambda=2.0,
                         objective="binary:logistic", eval_metric="logloss",
                         random_state=SEED, n_jobs=2, verbosity=0)


def logit():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, C=1.0))


def fit_predict(kind, tr, te, cols):
    Xtr, ytr, wtr = tr[cols].to_numpy(float), tr["label"].to_numpy(), tr["sample_weight"].to_numpy(float)
    Xte = te[cols].to_numpy(float)
    if kind == "xgb":
        m = xgb().fit(Xtr, ytr, sample_weight=wtr)
        return m.predict_proba(Xte)[:, 1]
    if kind == "logit":
        Xtr = np.nan_to_num(Xtr, nan=np.nanmedian(Xtr)); Xte = np.nan_to_num(Xte, nan=np.nanmedian(Xtr))
        m = logit()
        m.fit(Xtr, ytr, logisticregression__sample_weight=wtr)
        return m.predict_proba(Xte)[:, 1]
    raise ValueError(kind)


def metrics(y, p):
    y, p = np.asarray(y), np.asarray(p)
    if len(np.unique(y)) < 2:
        return dict(auc=None, pr_auc=None, brier=None, n=int(len(y)), base_rate=float(y.mean()))
    return dict(auc=round(float(roc_auc_score(y, p)), 3), pr_auc=round(float(average_precision_score(y, p)), 3),
                brier=round(float(brier_score_loss(y, p)), 3), n=int(len(y)), base_rate=round(float(y.mean()), 3))


def loo(df, group_col, kind, cols, shuffle=False, seed=SEED):
    """Hold out one group at a time; return pooled held-out predictions."""
    rng = np.random.default_rng(seed)
    d = df.reset_index(drop=True).copy()
    if shuffle:                                   # shuffle labels within each event: control
        d["label"] = d.groupby("event_id")["label"].transform(lambda s: rng.permutation(s.to_numpy()))
    pred = np.full(len(d), np.nan)
    for g in d[group_col].unique():
        te = d[group_col] == g
        tr = ~te
        if d.loc[tr, "label"].nunique() < 2:
            continue
        pred[te.to_numpy()] = fit_predict(kind, d[tr], d[te], cols)
    ok = ~np.isnan(pred)
    return d[ok], pred[ok]


def single_feature_auc(df, col):
    """Baseline (a): a raw feature used directly as the score (no fitting), so no CV needed."""
    x = df[col].fillna(df[col].median()).to_numpy(float)
    return roc_auc_score(df["label"], x)


def run_head(df, hazard):
    d = df[df.hazard == hazard].copy()
    n_ev = int(d[d.label == 1].event_id.nunique())
    res = dict(hazard=hazard, events=n_ev, rows=len(d), positives=int(d.label.sum()),
               note="illustrative: very few events" if n_ev < 20 else "")
    y_te, p = loo(d, "event_id", "xgb", DYN)
    res["xgb_loeo_dynamic"] = metrics(y_te.label, p)
    y_te, p = loo(d, "event_id", "xgb", DYN + STATIC)
    res["xgb_loeo_dynamic_plus_terrain"] = metrics(y_te.label, p)
    y_te, p = loo(d, "event_id", "logit", LOGIT)
    res["logit_rain_baseline_loeo"] = metrics(y_te.label, p)
    res["rain_24h_alone_auc"] = round(float(single_feature_auc(d, "rain_24h")), 3)
    res["antecedent_15d_alone_auc"] = round(float(single_feature_auc(d, "antecedent_rain_15d")), 3)
    aucs = []
    for s in range(3):
        y_te, p = loo(d, "event_id", "xgb", DYN, shuffle=True, seed=100 + s)
        aucs.append(metrics(y_te.label, p)["auc"])
    res["control_shuffled_labels_auc"] = [a for a in aucs]
    # LORO, per held-out region
    lor = {}
    for reg in sorted(d.region.unique()):
        te, tr = d[d.region == reg], d[d.region != reg]
        ev = int(te[te.label == 1].event_id.nunique())
        if tr.label.nunique() < 2 or te.label.nunique() < 2:
            lor[reg] = dict(events=ev, auc=None)
            continue
        m = metrics(te.label, fit_predict("xgb", tr, te, DYN))
        lor[reg] = dict(events=ev, auc=m["auc"], pr_auc=m["pr_auc"], base_rate=m["base_rate"])
    res["xgb_loro_by_region_illustrative"] = lor
    # importance from a model fit on all rows (descriptive only, not validation)
    m = xgb().fit(d[DYN].to_numpy(float), d["label"], sample_weight=d["sample_weight"])
    imp = sorted(zip(DYN, m.feature_importances_), key=lambda t: -t[1])[:5]
    res["top_features_full_fit_descriptive"] = [(k, round(float(v), 3)) for k, v in imp]
    return res


def main():
    df = pd.read_parquet(TABLE)
    df["event_id"] = df["event_id"].astype(str)
    out = dict(table=str(TABLE.relative_to(ROOT)), validation="leave-one-event-out (all rows of an event held out)",
               caveats=["small table; reanalysis rain under-reads extreme events",
                        "negatives are temporal only (same place), unrecorded events may hide among them",
                        "LORO is illustrative: no region has >= 15 events per hazard (v2 Sec. 15.3)",
                        "flood head uses point events, not micro-catchments"],
               heads=[run_head(df, h) for h in ("landslide", "flash_flood")])
    OUT.write_text(json.dumps(out, indent=2))
    for h in out["heads"]:
        print(f"\n=== {h['hazard']}: {h['events']} events, {h['rows']} rows, {h['positives']} positive rows ({h['note']})")
        for k in ("xgb_loeo_dynamic", "xgb_loeo_dynamic_plus_terrain", "logit_rain_baseline_loeo"):
            print(f"  {k:32s} {h[k]}")
        print(f"  rain_24h alone AUC = {h['rain_24h_alone_auc']}   antecedent_15d alone AUC = {h['antecedent_15d_alone_auc']}")
        print(f"  CONTROL shuffled-label AUC (3 seeds) = {h['control_shuffled_labels_auc']}")
        print("  top features (descriptive):", h["top_features_full_fit_descriptive"])
        print("  LORO by region (illustrative):")
        for r, v in h["xgb_loro_by_region_illustrative"].items():
            print(f"     {r:32s} events={v['events']:2d} auc={v.get('auc')} pr_auc={v.get('pr_auc')}")
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
