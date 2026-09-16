"""
run_chronos_inference.py -- Step 6b execution: actually run Chronos-Bolt
(previously build-only) zero-shot on the real GUARDIAN river WSE series,
producing a real 24-step forecast continuing from each station's last real
observed reading.

Chronos-Bolt is pretrained -- no training loop, this is inference only.
Univariate (rainfall covariate NOT used here -- base ChronosPipeline doesn't
support it, documented in prepare_chronos_input.py's manifest; the
AutoGluon-TimeSeries covariate path is a separate, much larger dependency
not run in this session).

HONESTY NOTE, disclosed in the output: forecasts continue from each
station's LAST REAL OBSERVED TIMESTAMP, which for most of these 12
real GUARDIAN stations is 2023-2026 (not "today") -- these are NOT live
forecasts for the current moment, just a real zero-shot continuation of
real historical data. Sparse stations (e.g. Bhavani Bridge, 18 points) are
flagged as low-confidence given how few real points anchor the forecast.

Output: data/multiregion/model_ready/chronos/predictions.json
  { item_id: {last_observed_time, last_observed_value_m, n_context_points,
              forecast_median_m: [...24], forecast_low_m/_high_m: [...24],
              model, caveat} }
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
CHRONOS_DIR = REPO_ROOT / "data" / "multiregion" / "model_ready" / "chronos"
TIMESERIES_CSV = CHRONOS_DIR / "timeseries_long.csv"
OUT_JSON = CHRONOS_DIR / "predictions.json"

PREDICTION_LENGTH = 24
MODEL_NAME = "amazon/chronos-bolt-base"
MIN_CONTEXT_POINTS = 10  # below this, forecast is too thin to be meaningful

CAVEAT_TEXT = (
    "Computed by Chronos-Bolt (pretrained, zero-shot time-series forecaster) "
    "continuing from this station's LAST REAL OBSERVED reading -- NOT a live "
    "forecast for the current moment. Univariate (rainfall not used as a "
    "covariate; base Chronos-Bolt API doesn't support it, see manifest.json)."
)


def main():
    from chronos import BaseChronosPipeline

    df = pd.read_csv(TIMESERIES_CSV, parse_dates=["timestamp"])
    print(f"Loaded {len(df)} rows across {df['item_id'].nunique()} series")

    print(f"Loading pretrained {MODEL_NAME} (zero-shot, no training)...")
    pipeline = BaseChronosPipeline.from_pretrained(MODEL_NAME, device_map="cpu")
    print("Loaded.")

    results = {}
    for item_id, group in df.groupby("item_id"):
        g = group.sort_values("timestamp")
        series = g["target_river_water_level_m"].ffill().dropna()
        if len(series) < MIN_CONTEXT_POINTS:
            print(f"  {item_id:24s} SKIPPED -- only {len(series)} real points (< {MIN_CONTEXT_POINTS})")
            continue

        context = torch.tensor(series.values[-2048:], dtype=torch.float32)
        last_time = g["timestamp"].iloc[-1]
        last_value = float(series.iloc[-1])

        quantiles, _mean = pipeline.predict_quantiles(
            inputs=context,
            prediction_length=PREDICTION_LENGTH,
            quantile_levels=[0.1, 0.5, 0.9],
        )
        q = quantiles[0].numpy()  # shape (prediction_length, 3)

        results[item_id] = {
            "last_observed_time": last_time.isoformat(),
            "last_observed_value_m": round(last_value, 3),
            "n_context_points": int(len(series)),
            "forecast_low_m": [round(float(v), 3) for v in q[:, 0]],
            "forecast_median_m": [round(float(v), 3) for v in q[:, 1]],
            "forecast_high_m": [round(float(v), 3) for v in q[:, 2]],
            "prediction_length_steps": PREDICTION_LENGTH,
            "model": f"Chronos-Bolt ({MODEL_NAME}, pretrained zero-shot)",
            "caveat": CAVEAT_TEXT,
        }
        print(f"  {item_id:24s} OK -- {len(series)} real context points, "
              f"last real={last_value:.2f}m @ {last_time}, "
              f"forecast median next-step={q[0,1]:.2f}m")

    OUT_JSON.write_text(json.dumps(results, indent=2))
    print(f"\nSaved {len(results)} real station forecasts -> {OUT_JSON}")


if __name__ == "__main__":
    main()
