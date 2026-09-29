"""
ml/dataset/explain.py -- per-prediction feature contributions (v2 Sec. 8.6).

Uses XGBoost's built-in exact TreeSHAP (`pred_contribs=True`), so no extra library is needed.
Contributions are in log-odds (margin) space and are additive: sum(contributions) + bias equals the
model's raw margin for that row.  Collinear features are also reported at GROUP level so no single
correlated feature appears to carry the weight (v2 Sec. 8.6).
"""
from __future__ import annotations

import pandas as pd
import xgboost as xgb

GROUPS = {
    "recent rain": ["rain_1h", "rain_3h", "rain_6h", "rain_12h", "rain_24h", "rain_max_1h_6h",
                    "era5_1d", "imerg_1d"],
    "antecedent rain": ["antecedent_rain_3d", "antecedent_rain_7d", "antecedent_rain_15d",
                        "era5_3d", "era5_7d", "era5_15d", "imerg_3d", "imerg_7d", "imerg_15d"],
    "soil moisture / saturation": ["soil_moisture_0_7", "soil_moisture_7_28", "sat_m"],
    "terrain": ["elevation_m", "slope_deg", "relief_m_440"],
    "physics": ["p_fs_lt1", "fs_p50", "r_int_caine", "r_int_fit"],
}


def contributions(model, X: pd.DataFrame) -> pd.DataFrame:
    """Per-row contributions (log-odds) with one column per feature plus 'bias'."""
    booster = model.get_booster() if hasattr(model, "get_booster") else model
    cols = list(X.columns)
    d = xgb.DMatrix(X.to_numpy(float), feature_names=cols)
    c = booster.predict(d, pred_contribs=True)
    return pd.DataFrame(c, columns=cols + ["bias"], index=X.index)


def group_contributions(contrib: pd.DataFrame) -> pd.DataFrame:
    """Sum contributions within feature groups; features in no group stay as themselves."""
    out, used = {}, set()
    for name, members in GROUPS.items():
        present = [m for m in members if m in contrib.columns]
        if present:
            out[name] = contrib[present].sum(axis=1)
            used.update(present)
    for c in contrib.columns:
        if c not in used:
            out[c] = contrib[c]
    return pd.DataFrame(out, index=contrib.index)


def top_reasons(row: pd.Series, n: int = 3) -> list[tuple[str, float]]:
    """The n largest-magnitude non-bias contributions for one row: [(name, log-odds), ...]."""
    r = row.drop(labels=["bias"], errors="ignore")
    order = r.abs().sort_values(ascending=False).index
    return [(k, round(float(r[k]), 4)) for k in order[:n]]
