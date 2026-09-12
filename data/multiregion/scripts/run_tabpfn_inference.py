"""
run_tabpfn_inference.py -- Step 6a execution: actually run TabPFN (previously
build-only, per user instruction) on the real multiregion event-centered
dataset, producing a real risk_score per historical event for the 9
non-Wayanad regions.

TabPFN is a pretrained tabular classifier -- .fit() is a fast in-context
pass (not a real training loop), so this is closer to "run inference" than
"train a model." Its predict_proba plugs directly into the SAME frozen
formula the live Wayanad model uses (imported, not re-derived):
  risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88

HARD CONSTRAINT / KNOWN CAVEAT (flagged repeatedly this session, still
unresolved -- user chose to proceed with disclosure rather than fix first):
negative samples in this dataset are 0% covered on rainfall_1h and
soil_saturation_ratio by construction (Step 5). TabPFN, like any classifier,
may partly learn "feature is null" as a decision signal rather than pure
flood physics. Every score this script produces is tagged with this caveat
in the output JSON -- the frontend must display it, not hide it.

Scope: fit on ALL 10 locations' real labelled rows (more real context =
better for TabPFN, which is a few-shot/in-context method), but only predict
+ store scores for the AT-EVENT ("tier"=="Red", sample_type=="positive")
snapshot of each real historical event in the 9 non-Wayanad regions --
Wayanad already has its own live XGBoost pilot, not touched here.

Output: data/multiregion/model_ready/tabpfn/predictions.json
  { "<UEI>::<region_key>": {risk_score, tier, tabpfn_class_probability, model, caveat} }
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from ml.models.train_fusion_model import compute_risk_score, derive_tier, TIER_TO_INT, INT_TO_TIER
from backend.seed_multiregion import REGIONS  # {region_key: (target_location, default_point)}

TABPFN_DIR = REPO_ROOT / "data" / "multiregion" / "model_ready" / "tabpfn"
TRAIN_CSV = TABPFN_DIR / "train.csv"
VAL_CSV = TABPFN_DIR / "val.csv"
OUT_JSON = TABPFN_DIR / "predictions.json"

FEATURE_COLS = [
    "elevation", "slope_deg", "aspect", "TWI", "TRI",
    "distance_to_river_m", "flow_accumulation_cells", "drainage_density_km_per_km2",
    "cwc_danger_level_m",
    "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h", "rainfall_72h_antecedent",
    "antecedent_precipitation_index", "rain_intensity_mm_hr",
    "soil_saturation_ratio",
    "river_water_level_m", "river_level_change_m_per_hr",
]

CAVEAT_TEXT = (
    "Computed by TabPFN (pretrained tabular classifier) on the real "
    "multiregion dataset. KNOWN LIMITATION, disclosed not hidden: negative "
    "training samples are 0% covered on rainfall/soil features by "
    "construction, so the model may partly reflect that pattern rather than "
    "pure flood physics. Missing feature values were median-imputed for "
    "model input only (see manifest); do not treat this score with the same "
    "confidence as Wayanad's live XGBoost pilot."
)

TARGET_TO_REGION_KEY = {target_loc: key for key, (target_loc, _default_pt) in REGIONS.items()}


def main():
    from tabpfn import TabPFNClassifier

    train_df = pd.read_csv(TRAIN_CSV)
    val_df = pd.read_csv(VAL_CSV)
    full_df = pd.concat([train_df, val_df], ignore_index=True)
    print(f"Loaded {len(full_df)} total rows ({len(train_df)} train + {len(val_df)} val)")

    X_full = full_df[FEATURE_COLS].copy()
    medians = X_full.median(numeric_only=True)
    n_null_before = int(X_full.isna().sum().sum())
    X_full = X_full.fillna(medians)
    print(f"Median-imputed {n_null_before} null feature values across {len(FEATURE_COLS)} columns "
          f"(model-input only, disclosed in output caveat)")

    y_full = full_df["tier_int"].astype(int)

    print("Fitting TabPFNClassifier (pretrained, in-context -- not a real training loop)...")
    clf = TabPFNClassifier()
    clf.fit(X_full.to_numpy(), y_full.to_numpy())
    print("Fit complete.")

    # Score only the real at-event snapshot (tier==Red, sample_type==positive)
    # for the 9 non-Wayanad regions -- Wayanad keeps its own live model.
    target_mask = (
        (full_df["sample_type"] == "positive")
        & (full_df["tier"] == "Red")
        & (full_df["region"] != "Wayanad")
    )
    target_df = full_df[target_mask].copy()
    print(f"Scoring {len(target_df)} real at-event snapshots across {target_df['region'].nunique()} regions")

    X_target = target_df[FEATURE_COLS].fillna(medians).to_numpy()
    proba = clf.predict_proba(X_target)

    results = {}
    for i, (_, row) in enumerate(target_df.iterrows()):
        proba_dict = {tier_int: float(proba[i, tier_int]) for tier_int in TIER_TO_INT.values()}
        risk_score = compute_risk_score(proba_dict)
        tier = derive_tier(risk_score)
        max_class_proba = float(max(proba[i]))

        region_key = TARGET_TO_REGION_KEY.get(row["region"])
        if region_key is None:
            continue
        full_key = f"{row['event_id']}::{region_key}"

        results[full_key] = {
            "risk_score": risk_score,
            "tier": tier,
            "tabpfn_class_probability": round(max_class_proba, 4),
            "model": "TabPFN (pretrained tabular classifier, run via Step 6a)",
            "caveat": CAVEAT_TEXT,
        }

    OUT_JSON.write_text(json.dumps(results, indent=2))
    print(f"\nSaved {len(results)} real per-event TabPFN scores -> {OUT_JSON}")

    print("\n" + "=" * 70)
    print("SUMMARY (real TabPFN output, at-event snapshots, 9 non-Wayanad regions)")
    print("=" * 70)
    by_region_tier = target_df.assign(
        tabpfn_tier=[results.get(f"{r['event_id']}::{TARGET_TO_REGION_KEY.get(r['region'], '?')}", {}).get("tier")
                     for _, r in target_df.iterrows()]
    )
    print(by_region_tier.groupby(["region", "tabpfn_tier"]).size())


if __name__ == "__main__":
    main()
