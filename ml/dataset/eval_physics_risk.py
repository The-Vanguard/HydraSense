"""
ml/dataset/eval_physics_risk.py -- how does the hand-set physics-first index do on the graded events?

The index has NO fitted parameters, so a plain AUC on the event table is meaningful (no train/test
split is needed).  Caveat stated in every result: the structure was chosen AFTER seeing that rain is
the best single feature on this same table (rain_24h alone = 0.66), so this is a sanity check, not a
clean out-of-sample test.  Terrain HAND is unavailable for these events (flood term = 0) and soil
parameters are the generic defaults, so this evaluates the landslide side.

Writes data/validation/physics_risk_eval.json.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import physics_features as pf                      # noqa: E402
from backend import physics_risk as pr             # noqa: E402

TABLE = ROOT / "data" / "events" / "training_table_v0p.parquet"
OUT = ROOT / "data" / "validation" / "physics_risk_eval.json"


def to_features(r) -> dict:
    return dict(rainfall_1h=r.rain_1h, rainfall_3h=r.rain_3h, rainfall_6h=r.rain_6h, rainfall_24h=r.rain_24h,
                rainfall_72h_antecedent=r.antecedent_rain_3d, soil_saturation_ratio=r.sat_m,
                slope_deg=r.slope_deg, has_local_calibration=False,
                soil_c_prime_kpa=pf.GENERIC_SOIL["cohesion_kpa"], soil_phi_deg=pf.GENERIC_SOIL["friction_angle_deg"],
                soil_z_m=pf.GENERIC_SOIL["soil_depth_m"], soil_gamma_kn_m3=pf.GENERIC_SOIL["unit_weight_kn_m3"])


def auc(y, s):
    y, s = np.asarray(y), np.asarray(s, dtype=float)
    ok = ~np.isnan(s)
    if ok.sum() < 10 or len(np.unique(y[ok])) < 2:
        return None
    return round(float(roc_auc_score(y[ok], s[ok])), 3)


def main():
    d = pd.read_parquet(TABLE)
    res = [pr.score_features(to_features(r), seed=i) for i, r in enumerate(d.itertuples())]
    d["index"] = [x["risk_score"] for x in res]
    d["trigger"] = [x["trigger"] for x in res]
    d["susceptibility_only"] = [100 * (0.5 * (x["slope_term"] or 0) + 0.5 * (x["p_fs_lt1"] or 0)) for x in res]
    d["tier"] = [x["tier"] for x in res]
    out = dict(rows=len(d), table=str(TABLE.relative_to(ROOT)),
               caveat=("structure chosen after seeing rain_24h is the best single feature on this table; "
                       "generic soil parameters; flood term unavailable (no HAND for these events)"),
               heads=[])
    for h in ("landslide", "flash_flood"):
        x = d[d.hazard == h]
        row = dict(hazard=h, events=int(x[x.label == 1].event_id.nunique()), rows=len(x),
                   auc=dict(index=auc(x.label, x["index"]), trigger_only=auc(x.label, x.trigger),
                            susceptibility_only=auc(x.label, x.susceptibility_only),
                            rain_24h_alone=auc(x.label, x.rain_24h), r_int_caine_alone=auc(x.label, x.r_int_caine)),
                   pr_auc_index=round(float(average_precision_score(x.label, x["index"])), 3),
                   base_rate=round(float(x.label.mean()), 3),
                   tier_counts_positive=x[x.label == 1].tier.value_counts().to_dict(),
                   tier_counts_negative=x[x.label == 0].tier.value_counts().to_dict())
        # per-event view: does the score rise toward onset?
        pos = x[x.label == 1].groupby("offset_h")["index"].median().round(1).sort_index(ascending=False)
        row["median_index_by_offset_h"] = {str(k): float(v) for k, v in pos.items()}
        out["heads"].append(row)
    OUT.write_text(json.dumps(out, indent=2))
    for h in out["heads"]:
        print(f"\n=== {h['hazard']}: {h['events']} events, {h['rows']} rows, base rate {h['base_rate']}")
        print("  AUC:", h["auc"], "| PR-AUC(index):", h["pr_auc_index"])
        print("  median index of positive rows by hours before onset:", h["median_index_by_offset_h"])
        print("  tiers among POSITIVE rows:", h["tier_counts_positive"])
        print("  tiers among NEGATIVE rows:", h["tier_counts_negative"])
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
