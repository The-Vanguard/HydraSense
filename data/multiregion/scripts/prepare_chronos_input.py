"""
prepare_chronos_input.py -- Step 6b: format real river-level (WSE) + rainfall
data as a time-series input for Chronos-Bolt. DOES NOT RUN Chronos -- writes
a long-format CSV and a manifest with exact commands.

REAL SUBSTITUTION, FLAGGED: the brief asked for "river discharge" as the
forecast target. river_discharge does not exist anywhere in this dataset --
confirmed unavailable (no rating curve) at every one of the 12 GUARDIAN
stations checked in Step 4. The only real target series is
river_water_level (WSE). Building this around discharge would mean
forecasting a series that was never fetched -- not done.

REAL CONSTRAINT ON "RAINFALL AS COVARIATE", FLAGGED: the base Chronos /
Chronos-Bolt zero-shot API (ChronosPipeline.predict()) is univariate --
it does not natively accept exogenous covariates. Genuine covariate support
requires AutoGluon-TimeSeries' TimeSeriesPredictor with Chronos-Bolt as one
model in an ensemble and rainfall passed as a known_covariate. This script
prepares data for that real path, not a fictional "just pass rainfall in"
API that doesn't exist in the public Chronos release.

Only locations/points with ANY real GUARDIAN river data are included
(Wayanad villages via Kabini/Kottathara, Idamalayar_Dam, Rudraprayag_town,
Joshimath, Badrinath, Gopeshwar via Karnaprayag/Nandprayag, Byrnihat) --
points with zero real river coverage are excluded, not filled with anything.

Output: data/multiregion/model_ready/chronos/timeseries_long.csv
  columns: item_id, timestamp, target (river_water_level_m), rainfall_mm (covariate)
"""

import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
RIVER_DIR = REPO_ROOT / "data" / "multiregion" / "river"
WEATHER_DIR = REPO_ROOT / "data" / "multiregion" / "weather"
OUT_DIR = REPO_ROOT / "data" / "multiregion" / "model_ready" / "chronos"

# station WSE file -> (item_id, region, rainfall-lookup point in that region's rainfall file)
STATIONS = {
    "wse_Kabini_Reservoir.json":    ("Kabini_Reservoir", "wayanad", "Chooralmala"),
    "wse_KOTTATHARA.json":          ("Kottathara", "wayanad", "Chooralmala"),
    "wse_Idamalayar_Reservoir.json": ("Idamalayar_Reservoir", "idukki", "Idamalayar_Dam"),
    "wse_Rudraprayag_A.json":       ("Rudraprayag_A", "rudraprayag", "Rudraprayag_town"),
    "wse_Rudraprayag_M.json":       ("Rudraprayag_M", "rudraprayag", "Rudraprayag_town"),
    "wse_Rudraprayag_conf.json":    ("Rudraprayag_conf", "rudraprayag", "Rudraprayag_town"),
    "wse_Joshimath.json":           ("Joshimath", "chamoli", "Joshimath"),
    "wse_Badrinath.json":           ("Badrinath", "chamoli", "Badrinath"),
    "wse_Karnaprayag_A.json":       ("Karnaprayag_A", "chamoli", "Gopeshwar"),
    "wse_Karnaprayag_P.json":       ("Karnaprayag_P", "chamoli", "Gopeshwar"),
    "wse_Nandprayag.json":          ("Nandprayag", "chamoli", "Gopeshwar"),
    "wse_Byrnihat.json":            ("Byrnihat", "ribhoi", "Byrnihat"),
    "wse_Lachen.json":              ("Lachen", "sikkim_mangan", "Lachen"),
    # Bhavani stations: real Nilgiris-region river data, NOT used as a Step-5
    # flash-flood-risk proxy for Ooty/Coonoor/Gudalur (too far downstream/
    # different catchment position, flagged in build_event_centered_samples.py)
    # but still a legitimate independent river-level forecasting target --
    # included here since this script's own inclusion rule is "any real
    # GUARDIAN river data," not "matches a Step-5 point."
    "wse_Bhavani_Bridge.json":      ("Bhavani_Bridge", "nilgiris", "Gudalur"),
    "wse_Bhavani_Sagar_Dam.json":   ("Bhavani_Sagar_Dam", "nilgiris", "Gudalur"),
    "wse_Melli.json":               ("Melli", "darjeeling_kalimpong", "Kalimpong_town_district_HQ"),
    "wse_Dibrugarh.json":           ("Dibrugarh", "dhemaji", "Dhemaji_town_district_HQ"),
    "wse_Subansiri_Lower_Dam.json": ("Subansiri_Lower_Dam", "dhemaji", "Gogamukh"),
    # Risiang: real station, ~1200m elevation -- upstream hill terrain, not a
    # valid proxy for lowland Jonai (per build_event_centered_samples.py's
    # reasoning). Not included here either, same call, kept as raw data only.
}


def load_rainfall_lookup(region: str, point: str) -> dict:
    p = WEATHER_DIR / f"rainfall_historical_{region}.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    for loc in data["locations"]:
        if loc["location"] == point:
            return dict(zip(loc["series"]["time"], loc["series"]["precipitation_mm"]))
    return {}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    skipped = []

    for fname, (item_id, region, rain_point) in STATIONS.items():
        p = RIVER_DIR / fname
        if not p.exists():
            skipped.append(item_id)
            continue
        wse_data = json.loads(p.read_text())
        times = wse_data["series"]["time"]
        wse_vals = wse_data["series"]["wse_m"]
        rain_lookup = load_rainfall_lookup(region, rain_point)

        n_rain_hit = 0
        for t, wse in zip(times, wse_vals):
            if wse is None:
                continue
            rain = rain_lookup.get(pd.Timestamp(t).strftime("%Y-%m-%dT%H:00"))
            if rain is not None:
                n_rain_hit += 1
            rows.append({"item_id": item_id, "region": region, "timestamp": t,
                         "target_river_water_level_m": wse, "rainfall_mm": rain})
        print(f"{item_id:20s} region={region:14s} {len(times)} WSE points, "
              f"{n_rain_hit} with real rainfall overlap ({n_rain_hit/max(len(times),1)*100:.1f}%)")

    df = pd.DataFrame(rows)
    out_path = OUT_DIR / "timeseries_long.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} rows across {df['item_id'].nunique()} series -> {out_path}")
    if skipped:
        print(f"Skipped (no real river file found): {skipped}")

    manifest = {
        "n_series": int(df["item_id"].nunique()),
        "series_ids": sorted(df["item_id"].unique().tolist()),
        "target_column": "target_river_water_level_m",
        "target_note": (
            "river_discharge was requested in the original brief but does not exist -- "
            "confirmed unavailable (no rating curve) at every GUARDIAN station checked. "
            "Forecasting river_water_level (WSE) instead, the only real target series available."
        ),
        "covariate_column": "rainfall_mm",
        "covariate_note": (
            "rainfall_mm is real ERA5 archive data only where it overlaps GUARDIAN's WSE "
            "coverage window (2020+ for all stations); null elsewhere in this file, not filled."
        ),
        "rainfall_as_covariate_caveat": (
            "Base Chronos-Bolt zero-shot inference (ChronosPipeline.predict()) is UNIVARIATE -- "
            "it does not accept rainfall as an input. Genuine covariate support requires "
            "AutoGluon-TimeSeries' TimeSeriesPredictor with Chronos-Bolt as the model and "
            "rainfall passed via known_covariates. Both real commands given below."
        ),
        "how_to_run_zero_shot_univariate": {
            "install": "pip install chronos-forecasting torch",
            "python": (
                "import pandas as pd, torch\n"
                "from chronos import ChronosPipeline\n\n"
                "df = pd.read_csv('timeseries_long.csv')\n"
                "series = df[df['item_id']=='Joshimath'].sort_values('timestamp')\n"
                "context = torch.tensor(series['target_river_water_level_m'].ffill().values, dtype=torch.float32)\n\n"
                "pipeline = ChronosPipeline.from_pretrained('amazon/chronos-bolt-base', device_map='cpu')\n"
                "forecast = pipeline.predict(context=context, prediction_length=24)  # next 24 hours\n"
                "# forecast shape: (num_series=1, num_samples, prediction_length)\n"
            ),
            "expected_output_shape": "(1, num_samples, 24) tensor of quantile sample forecasts for the next 24 hours of WSE",
        },
        "how_to_run_with_rainfall_covariate": {
            "install": "pip install autogluon.timeseries",
            "python": (
                "from autogluon.timeseries import TimeSeriesDataFrame, TimeSeriesPredictor\n\n"
                "df = TimeSeriesDataFrame.from_data_frame(\n"
                "    pd.read_csv('timeseries_long.csv'),\n"
                "    id_column='item_id', timestamp_column='timestamp',\n"
                ")\n"
                "predictor = TimeSeriesPredictor(target='target_river_water_level_m', prediction_length=24,\n"
                "                                 known_covariates_names=['rainfall_mm'])\n"
                "predictor.fit(df, presets='bolt_base', hyperparameters={'Chronos': {'model_path': 'bolt_base'}})\n"
                "forecast = predictor.predict(df)\n"
            ),
            "expected_output_shape": "TimeSeriesDataFrame, one row per (item_id, forecast timestamp), columns = quantile forecasts (0.1..0.9) of river_water_level_m",
        },
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Manifest -> {OUT_DIR / 'manifest.json'}")
    print("\nNOT RUNNING Chronos-Bolt -- per instructions, stopping here.")


if __name__ == "__main__":
    main()
