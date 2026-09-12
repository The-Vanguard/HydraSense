"""
compute_tabpfn_feature_importance.py -- Step 6c: GLOBAL permutation feature
importance for the TabPFN model already fit in run_tabpfn_inference.py.

Honesty note: TabPFN has no built-in per-prediction attribution (unlike the
live Wayanad XGBoost model's SHAP-style top_contributing_features). This is a
GLOBAL ranking -- how much shuffling each feature degrades the model's
accuracy across a held-out sample of real validation rows -- not a per-event
explanation. It is the same ranking for every event on the frontend, labeled
as such.

Uses a random subsample of val.csv (not the full set) because TabPFN
inference is slow and permutation importance requires many repeated predict
calls (n_repeats * n_features); this is disclosed in the output caveat.

Output: data/multiregion/model_ready/tabpfn/feature_importance.json
  { features: [{name, importance_mean, importance_std}, ...] (desc order),
    n_eval_rows, n_repeats, caveat }
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

REPO_ROOT = Path(__file__).resolve().parents[3]
TABPFN_DIR = REPO_ROOT / "data" / "multiregion" / "model_ready" / "tabpfn"
TRAIN_CSV = TABPFN_DIR / "train.csv"
VAL_CSV = TABPFN_DIR / "val.csv"
OUT_JSON = TABPFN_DIR / "feature_importance.json"

FEATURE_COLS = [
    "elevation", "slope_deg", "aspect", "TWI", "TRI",
    "distance_to_river_m", "flow_accumulation_cells", "drainage_density_km_per_km2",
    "cwc_danger_level_m",
    "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h", "rainfall_72h_antecedent",
    "antecedent_precipitation_index", "rain_intensity_mm_hr",
    "soil_saturation_ratio",
    "river_water_level_m", "river_level_change_m_per_hr",
]

N_EVAL_ROWS = 40   # subsample of val.csv -- TabPFN predict on the full 5498-row
                   # context is slow on CPU; 150 rows x 3 repeats ran 70+ min with
                   # no result, so this shrinks the eval sample instead of the
                   # context TabPFN fits on (the real fit stays on all 5498 rows)
N_REPEATS = 2
RANDOM_STATE = 42

CAVEAT_TEXT = (
    "GLOBAL permutation feature importance -- how much shuffling each "
    "feature degrades TabPFN's accuracy on a real held-out sample. This is "
    "the SAME ranking shown for every event (unlike Wayanad's live "
    "per-prediction SHAP-style contributing features), because TabPFN has "
    "no built-in per-prediction attribution. Computed on a random "
    f"{N_EVAL_ROWS}-row subsample of real validation data (not the full "
    "set) because TabPFN inference is slow; ranking may shift slightly with "
    "a different subsample."
)


def main():
    from tabpfn import TabPFNClassifier

    train_df = pd.read_csv(TRAIN_CSV)
    val_df = pd.read_csv(VAL_CSV)
    full_df = pd.concat([train_df, val_df], ignore_index=True)

    X_full = full_df[FEATURE_COLS].copy()
    medians = X_full.median(numeric_only=True)
    X_full = X_full.fillna(medians)
    y_full = full_df["tier_int"].astype(int)

    print("Fitting TabPFNClassifier (same as run_tabpfn_inference.py)...")
    clf = TabPFNClassifier()
    clf.fit(X_full.to_numpy(), y_full.to_numpy())
    print("Fit complete.")

    rng = np.random.RandomState(RANDOM_STATE)
    eval_df = val_df.sample(n=min(N_EVAL_ROWS, len(val_df)), random_state=rng)
    X_eval = eval_df[FEATURE_COLS].fillna(medians).to_numpy()
    y_eval = eval_df["tier_int"].astype(int).to_numpy()

    print(f"Running permutation importance on {len(X_eval)} real held-out rows, "
          f"{N_REPEATS} repeats x {len(FEATURE_COLS)} features "
          f"({N_REPEATS * len(FEATURE_COLS)} extra TabPFN predict calls -- slow)...")
    result = permutation_importance(
        clf, X_eval, y_eval,
        n_repeats=N_REPEATS, random_state=RANDOM_STATE, scoring="accuracy",
    )

    ranked = sorted(
        zip(FEATURE_COLS, result.importances_mean, result.importances_std),
        key=lambda t: t[1], reverse=True,
    )
    features = [
        {"name": name, "importance_mean": round(float(m), 5), "importance_std": round(float(s), 5)}
        for name, m, s in ranked
    ]

    out = {
        "features": features,
        "n_eval_rows": len(X_eval),
        "n_repeats": N_REPEATS,
        "model": "TabPFN (pretrained tabular classifier)",
        "caveat": CAVEAT_TEXT,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2))
    print(f"\nSaved global feature importance -> {OUT_JSON}")
    for f in features[:8]:
        print(f"  {f['name']:32s} {f['importance_mean']:.5f} +/- {f['importance_std']:.5f}")


if __name__ == "__main__":
    main()
