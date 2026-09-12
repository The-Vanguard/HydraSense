"""
isolation_forest_validation.py -- Step 7: sklearn IsolationForest anomaly
detection against the existing simulated Phase 10 IoT telemetry.

Reuses iot/simulator.py's ESCALATION_CURVE data directly (imported, not
copied/modified) -- this IS the "existing simulated Phase 10 IoT telemetry"
the brief asked to validate against. All values were already labeled
SIMULATED in that file (SRS.md Section 16 / CLAUDE.md); training an
anomaly detector on them doesn't change that label or claim they're real.

Separate concern from the flood/landslide hazard model -- this only checks
whether IsolationForest can distinguish Stage 1 (Normal) baseline sensor
behavior from the later escalation stages (rain spike, saturation, slope
response) and the Stage-3 sensor dropout. It does not touch tier/risk_score.

Method:
  1. Train IsolationForest on Stage 1 (Normal) readings only, replicated
     with realistic per-sensor Gaussian jitter across many synthetic ticks
     (the simulator itself only ever emits fixed-value readings per stage --
     jitter is added here purely to give the model something to fit besides
     5 identical points; magnitude is small and documented, not a new
     synthetic disaster scenario).
  2. Score every reading from all 5 real stages (unjittered, the simulator's
     actual defined values) against that trained model.
  3. Report contamination-free anomaly scores stage-by-stage.

HARD CONSTRAINT (CLAUDE.md): this file is new (Phase 10 territory, owned by
Guhan-10 per CLAUDE.md's team-role table -- this session's git identity).
iot/simulator.py itself is NOT modified.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulator import ESCALATION_CURVE, ALL_PILOT_HEXES, DEVICE_DROPOUT_HEX  # real, existing Phase 10 data

RANDOM_SEED = 42
N_TRAIN_REPLICAS = 200      # synthetic ticks of Stage-1 baseline to fit on
JITTER_STD = {"rainfall": 0.05, "soil_moisture": 0.01, "tilt": 0.02}  # small, documented, not a new scenario


def stage_to_rows(stage, dropout_active: bool) -> list[dict]:
    rows = []
    for hex_id, sensors in stage.readings.items():
        if dropout_active and hex_id == DEVICE_DROPOUT_HEX:
            continue
        for sensor_type, value in sensors.items():
            rows.append({
                "stage": stage.stage_number, "stage_name": stage.name,
                "hex_id": hex_id, "sensor_type": sensor_type, "value": value,
            })
    return rows


def main():
    rng = np.random.RandomState(RANDOM_SEED)

    # ---- Build training set: Stage 1 (Normal) only, jittered ----
    stage1 = ESCALATION_CURVE[0]
    train_rows = []
    for _ in range(N_TRAIN_REPLICAS):
        for hex_id, sensors in stage1.readings.items():
            for sensor_type, value in sensors.items():
                noise = rng.normal(0, JITTER_STD[sensor_type])
                train_rows.append({"hex_id": hex_id, "sensor_type": sensor_type, "value": max(0.0, value + noise)})
    train_df = pd.DataFrame(train_rows)
    print(f"Training set: {len(train_df)} jittered Stage-1 (Normal) readings from real simulator baseline values")

    # One IsolationForest per sensor_type -- rainfall/soil_moisture/tilt have very
    # different scales (mm/hr vs 0-1 fraction vs degrees), sharing one model across
    # them would let scale dominate the anomaly score instead of behavior.
    models = {}
    for sensor_type in ["rainfall", "soil_moisture", "tilt"]:
        X = train_df.loc[train_df["sensor_type"] == sensor_type, ["value"]].to_numpy()
        clf = IsolationForest(n_estimators=200, contamination="auto", random_state=RANDOM_SEED)
        clf.fit(X)
        models[sensor_type] = clf
        print(f"  Fitted IsolationForest for '{sensor_type}' on {len(X)} points, "
              f"train range [{X.min():.3f}, {X.max():.3f}]")

    # ---- Score every REAL stage's REAL defined values (no jitter) ----
    dropout_active = False
    all_scored = []
    for stage in ESCALATION_CURVE:
        if stage.dropout_starts:
            dropout_active = True
        rows = stage_to_rows(stage, dropout_active)
        for r in rows:
            clf = models[r["sensor_type"]]
            score = clf.decision_function([[r["value"]]])[0]   # >0 normal, <0 anomalous
            pred = clf.predict([[r["value"]]])[0]                # 1 normal, -1 anomaly
            all_scored.append({**r, "anomaly_score": round(float(score), 4), "is_anomaly": pred == -1})

    scored_df = pd.DataFrame(all_scored)

    print("\n" + "=" * 78)
    print("STEP 7 -- IsolationForest anomaly scores per stage (real simulator values)")
    print("=" * 78)
    for stage_num in scored_df["stage"].unique():
        s = scored_df[scored_df["stage"] == stage_num]
        stage_name = s["stage_name"].iloc[0]
        n_anom = s["is_anomaly"].sum()
        print(f"\nStage {stage_num} ({stage_name}): {n_anom}/{len(s)} readings flagged anomalous")
        for _, row in s.iterrows():
            flag = "ANOMALY" if row["is_anomaly"] else "normal "
            print(f"    {row['hex_id'][:10]}.. {row['sensor_type']:14s} = {row['value']:6.2f}  "
                  f"score={row['anomaly_score']:+.3f}  [{flag}]")

    out_path = Path(__file__).resolve().parent / "isolation_forest_scores.csv"
    scored_df.to_csv(out_path, index=False)
    print(f"\nSaved full scored output -> {out_path}")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    summary = scored_df.groupby("stage_name")["is_anomaly"].agg(["sum", "count"])
    print(summary)
    print(
        "\nExpected pattern: Stage 1 near-0 anomalies (it's what the model trained on); "
        "anomaly rate should rise through Stages 2-4 as rainfall/soil_moisture/tilt "
        "move away from baseline; Stage 5 should match Stage 4 (same held values)."
    )


if __name__ == "__main__":
    main()
