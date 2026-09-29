"""
ml/dataset/physics_features.py -- v2 engineered features for the landslide head.

  sat_m          degree of saturation m from Open-Meteo soil moisture (theta) via
                 m = clip((theta - theta_r) / (theta_sat - theta_r), 0, 1).
                 theta_r / theta_sat are PROVISIONAL constants (no per-soil calibration).
  p_fs_lt1       P(FS < 1) from backend.engines.run_e2_landslide (infinite slope, Monte Carlo),
                 with GENERIC soil parameters unless the caller passes local ones.  Flagged
                 `fs_param_source = generic_default`; soil depth is a default, not a measurement.
  r_int_caine    max over durations D of I_obs(D) / I_thr(D) with the PUBLISHED global Caine (1980)
                 threshold I = 14.82 D^-0.39 (mm/h, h).  No fitting -> no leakage.
  r_int_fit      same ratio, but the threshold I = a D^-b is fitted (5th-percentile quantile
                 regression in log-log) on TRAINING-fold positives only (v2 Sec. 7.2.3).  It must
                 be recomputed inside every validation fold; never fit on all events then test.

Pure functions; no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.engines import compute_id_threshold, run_e2_landslide  # noqa: E402

# provisional soil-water constants (m3/m3) -- see docstring
THETA_R = 0.05
THETA_SAT = 0.55

# generic soil parameters (same defaults the engine tests use); depth is a DEFAULT, flagged
GENERIC_SOIL = dict(soil_depth_m=2.5, cohesion_kpa=8.0, friction_angle_deg=28.0, unit_weight_kn_m3=18.5)
FS_PARAM_SOURCE = "generic_default"

# duration (h) -> table column holding the rain total over that duration
DURATION_COLS = {1: "rain_1h", 3: "rain_3h", 6: "rain_6h", 12: "rain_12h", 24: "rain_24h",
                 72: "antecedent_rain_3d"}


def saturation_from_theta(theta: float) -> float:
    if theta is None or theta != theta:
        return float("nan")
    return float(np.clip((theta - THETA_R) / (THETA_SAT - THETA_R), 0.0, 1.0))


def p_fs_lt1(slope_deg: float, theta_mean: float, has_local_calibration: bool = False,
             seed: int = 0, soil: dict | None = None) -> tuple[float, float]:
    """Return (P(FS<1), FS median).  NaN if slope or soil moisture is unknown (never defaulted)."""
    m = saturation_from_theta(theta_mean)
    if slope_deg is None or slope_deg != slope_deg or m != m:
        return float("nan"), float("nan")
    np.random.seed(seed)                                # engine draws from the global RNG
    out = run_e2_landslide(slope_deg=slope_deg, saturation_ratio=m,
                           has_local_calibration=has_local_calibration, num_samples=400,
                           **(soil or GENERIC_SOIL))
    return float(out["p_fs_less_than_1"]), float(out["factor_of_safety"])


def intensities(df: pd.DataFrame) -> pd.DataFrame:
    """I_obs(D) = rain_D / D in mm/h, one column per duration."""
    return pd.DataFrame({D: df[c].to_numpy(float) / D for D, c in DURATION_COLS.items()}, index=df.index)


def rint_caine(df: pd.DataFrame) -> np.ndarray:
    I = intensities(df)
    ratios = np.column_stack([[compute_id_threshold(v, D) if v > 0 else 0.0 for v in I[D].to_numpy()]
                              for D in DURATION_COLS])
    return ratios.max(axis=1)


def fit_id_threshold(train: pd.DataFrame, quantile: float = 0.05) -> tuple[float, float]:
    """
    Fit log10 I = log10(alpha) - beta log10 D as a lower-envelope (quantile) regression on the
    rain observed just before onset (smallest offset_h row of each training positive event).
    Returns (alpha, beta) with I_thr(D) = alpha * D**-beta.
    """
    from sklearn.linear_model import QuantileRegressor
    pos = train[train.label == 1].sort_values("offset_h").groupby("event_id").head(1)
    I = intensities(pos)
    xs, ys = [], []
    for D in DURATION_COLS:
        v = I[D].to_numpy()
        ok = v > 0
        xs += [np.log10(D)] * int(ok.sum())
        ys += list(np.log10(v[ok]))
    if len(xs) < 10:
        return float("nan"), float("nan")
    q = QuantileRegressor(quantile=quantile, alpha=0.0, solver="highs")
    q.fit(np.array(xs).reshape(-1, 1), np.array(ys))
    return float(10 ** q.intercept_), float(-q.coef_[0])


def rint_fit(df: pd.DataFrame, alpha: float, beta: float) -> np.ndarray:
    if alpha != alpha or beta != beta:
        return np.full(len(df), np.nan)
    I = intensities(df)
    return np.column_stack([I[D].to_numpy() / (alpha * D ** (-beta)) for D in DURATION_COLS]).max(axis=1)


def add_static_physics(df: pd.DataFrame) -> pd.DataFrame:
    """Add sat_m, p_fs_lt1, fs_p50, r_int_caine (no fitting) and the parameter-source flag."""
    d = df.copy()
    theta = d[["soil_moisture_0_7", "soil_moisture_7_28"]].mean(axis=1)
    d["sat_m"] = theta.map(saturation_from_theta)
    res = [p_fs_lt1(s, t, False, seed=1000 + i) for i, (s, t) in enumerate(zip(d["slope_deg"], theta))]
    d["p_fs_lt1"] = [r[0] for r in res]
    d["fs_p50"] = [r[1] for r in res]
    d["fs_param_source"] = FS_PARAM_SOURCE
    d["r_int_caine"] = rint_caine(d)
    return d
