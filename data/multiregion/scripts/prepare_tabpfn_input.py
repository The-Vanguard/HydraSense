"""
prepare_tabpfn_input.py -- Step 6a: format the real Step-5 event-centered
dataset (3,148 rows, 5 locations) for TabPFN. DOES NOT RUN TABPFN -- writes
train/val CSVs and a manifest with the exact commands to run it yourself.

Target: tier_int (0=Green,1=Yellow,2=Orange,3=Red) -- matches the frozen
risk_score formula in CLAUDE.md (risk_score = P(Green)*15 + P(Yellow)*42 +
P(Orange)*64 + P(Red)*88, from predict_proba), so TabPFN's 4-class
predict_proba output plugs directly into that existing formula unchanged.

Split: GROUPED BY event_id, not random-row. The 6 snapshots of one event
are strongly correlated (same terrain, same storm) -- a random row split
would leak the same event across train and val. 80/20 split by unique
event_id (negatives, which have event_id=None, are split independently by
row since they aren't part of any event group).

HONEST DATA-QUALITY NOTE (carried into the manifest, not hidden): negative
rows are 0% covered on rainfall_1h/soil_saturation_ratio by construction
(flagged in Step 5 and in this session's prior turns). Training on this
file as-is risks the model learning "feature is null" as its decision rule
instead of real flood physics -- documented here, not fixed here, since the
simulation step to address it is explicitly deferred to the user's call.

river_discharge is dropped entirely -- 100% null, confirmed unavailable at
every GUARDIAN station checked. Including an all-null column would be
misleading, not informative.
"""

import json
from pathlib import Path

import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
IN_PARQUET = REPO_ROOT / "data" / "multiregion" / "events" / "event_centered_samples_10locations.parquet"
OUT_DIR = REPO_ROOT / "data" / "multiregion" / "model_ready" / "tabpfn"

FEATURE_COLS = [
    "elevation", "slope_deg", "aspect", "TWI", "TRI",
    "distance_to_river_m", "flow_accumulation_cells", "drainage_density_km_per_km2",
    "cwc_danger_level_m",
    "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h", "rainfall_72h_antecedent",
    "antecedent_precipitation_index", "rain_intensity_mm_hr",
    "soil_saturation_ratio",
    "river_water_level_m", "river_level_change_m_per_hr",
]
TARGET_COL = "tier_int"
ID_COLS = ["region", "point", "event_id", "snapshot_timestamp", "sample_type", "tier"]

RANDOM_SEED = 42
VAL_FRACTION = 0.20


def main():
    df = pd.read_parquet(IN_PARQUET)
    print(f"Loaded {len(df)} rows from {IN_PARQUET}")

    # Grouped split by event_id (positives); negatives (event_id is None) split by row.
    rng = np.random.RandomState(RANDOM_SEED)

    pos_event_ids = np.array(df.loc[df["event_id"].notna(), "event_id"].unique().tolist())
    rng.shuffle(pos_event_ids)
    n_val_events = max(1, int(len(pos_event_ids) * VAL_FRACTION))
    val_event_ids = set(pos_event_ids[:n_val_events])

    neg_idx = df.index[df["event_id"].isna()].to_numpy().copy()
    rng.shuffle(neg_idx)
    n_val_neg = max(1, int(len(neg_idx) * VAL_FRACTION))
    val_neg_idx = set(neg_idx[:n_val_neg])

    is_val = df["event_id"].isin(val_event_ids) | df.index.isin(val_neg_idx)
    train_df = df[~is_val].copy()
    val_df = df[is_val].copy()

    print(f"Train: {len(train_df)} rows ({train_df['event_id'].nunique()} events)")
    print(f"Val:   {len(val_df)} rows ({val_df['event_id'].nunique()} events)")
    print("Verifying no event_id overlap between train/val:",
          "OK" if set(train_df['event_id'].dropna()) & set(val_df['event_id'].dropna()) == set() else "LEAK DETECTED")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for name, split_df in [("train", train_df), ("val", val_df)]:
        out = split_df[ID_COLS + FEATURE_COLS + [TARGET_COL]].copy()
        out_path = OUT_DIR / f"{name}.csv"
        out.to_csv(out_path, index=False)
        n_null_feats = out[FEATURE_COLS].isna().mean().mean() * 100
        print(f"  {name}.csv -> {out_path}  ({len(out)} rows, {n_null_feats:.1f}% avg feature nullness)")

    manifest = {
        "feature_columns": FEATURE_COLS,
        "target_column": TARGET_COL,
        "target_meaning": {0: "Green", 1: "Yellow", 2: "Orange", 3: "Red"},
        "id_columns_not_for_training": ID_COLS,
        "train_rows": len(train_df), "val_rows": len(val_df),
        "train_events": int(train_df["event_id"].nunique()), "val_events": int(val_df["event_id"].nunique()),
        "split_method": "grouped by event_id (80/20), negatives split independently by row",
        "risk_score_formula_from_predict_proba": "risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88",
        "known_data_quality_issue": (
            "Negative rows (sample_type=negative) are 0% covered on rainfall_1h and "
            "soil_saturation_ratio by construction (Step 5). A model trained on this file "
            "as-is may learn feature-nullness as its decision boundary rather than real "
            "flood physics. This is documented, not fixed, here -- the fix (simulated "
            "baseline values for negatives) is deferred pending explicit user go-ahead."
        ),
        "river_discharge_excluded": "100% null at every location -- confirmed unavailable, not included as a feature.",
        "how_to_run_tabpfn": {
            "install": "pip install tabpfn",
            "python": (
                "import pandas as pd\n"
                "from tabpfn import TabPFNClassifier\n\n"
                "train = pd.read_csv('train.csv')\n"
                "val = pd.read_csv('val.csv')\n"
                "feature_cols = " + json.dumps(FEATURE_COLS) + "\n"
                "X_train, y_train = train[feature_cols], train['tier_int']\n"
                "X_val, y_val = val[feature_cols], val['tier_int']\n\n"
                "clf = TabPFNClassifier()  # pretrained, no hyperparameter tuning\n"
                "clf.fit(X_train, y_train)\n"
                "proba = clf.predict_proba(X_val)  # shape (n_val, 4), columns ordered [Green,Yellow,Orange,Red]\n"
                "risk_score = proba @ [15, 42, 64, 88]\n"
            ),
            "expected_output_shape": f"predict_proba: ({len(val_df)}, 4) array; risk_score: ({len(val_df)},) array in [15, 88]",
            "sanity_check": (
                "Compare mean risk_score for val rows where tier=='Red' vs tier=='Green'. "
                "Red should average noticeably higher than Green. If they're close or inverted, "
                "the model likely learned the rainfall/soil nullness pattern instead of real signal "
                "(see known_data_quality_issue above) -- this is the exact failure mode discussed "
                "earlier in this session."
            ),
        },
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest -> {OUT_DIR / 'manifest.json'}")
    print("\nNOT RUNNING TabPFN -- per instructions, stopping here. Commands above are ready to run yourself.")


if __name__ == "__main__":
    main()
