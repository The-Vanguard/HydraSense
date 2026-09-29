"""tests/test_physics_features.py -- ml/dataset/physics_features.py (pure, no network)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml" / "dataset"))
pytest.importorskip("sklearn")
import physics_features as pf  # noqa: E402


def row(**kw):
    base = dict(rain_1h=0, rain_3h=0, rain_6h=0, rain_12h=0, rain_24h=0, antecedent_rain_3d=0,
                label=1, offset_h=6, event_id="e")
    base.update(kw)
    return base


def test_saturation_clips_and_handles_nan():
    assert pf.saturation_from_theta(0.0) == 0.0
    assert pf.saturation_from_theta(0.9) == 1.0
    assert pf.saturation_from_theta(0.30) == pytest.approx(0.5)
    assert np.isnan(pf.saturation_from_theta(float("nan")))


def test_p_fs_unknown_inputs_are_nan_not_defaulted():
    assert np.isnan(pf.p_fs_lt1(float("nan"), 0.4)[0])
    assert np.isnan(pf.p_fs_lt1(20.0, float("nan"))[0])


def test_p_fs_reproducible_and_monotone_in_slope_and_wetness():
    a = pf.p_fs_lt1(30.0, 0.45, seed=7)
    assert a == pf.p_fs_lt1(30.0, 0.45, seed=7)                         # seeded -> reproducible
    assert pf.p_fs_lt1(40.0, 0.45, seed=7)[0] >= pf.p_fs_lt1(20.0, 0.45, seed=7)[0]
    assert pf.p_fs_lt1(30.0, 0.55, seed=7)[0] >= pf.p_fs_lt1(30.0, 0.20, seed=7)[0]
    assert pf.p_fs_lt1(3.0, 0.5, seed=7)[0] == 0.0                      # too flat to fail


def test_rint_caine_matches_published_relation():
    # 6 h at Caine threshold intensity 14.82 * 6**-0.39 mm/h => ratio 1 on that duration
    i_thr = 14.82 * 6 ** -0.39
    df = pd.DataFrame([row(rain_6h=i_thr * 6)])
    assert pf.rint_caine(df)[0] == pytest.approx(1.0, rel=1e-6)
    assert pf.rint_caine(pd.DataFrame([row()]))[0] == 0.0                # no rain -> 0


def test_fitted_threshold_uses_training_positives_only():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(30):
        scale = rng.uniform(0.5, 2.0)
        rows.append(row(event_id=f"e{i}", rain_1h=5 * scale, rain_3h=9 * scale, rain_6h=14 * scale,
                        rain_12h=20 * scale, rain_24h=30 * scale, antecedent_rain_3d=50 * scale))
    tr = pd.DataFrame(rows)
    a1, b1 = pf.fit_id_threshold(tr)
    # negatives and later-offset rows must not change the fit
    extra = tr.copy(); extra["label"] = 0
    extra2 = tr.copy(); extra2["offset_h"] = 72
    a2, b2 = pf.fit_id_threshold(pd.concat([tr, extra]))
    assert (a1, b1) == pytest.approx((a2, b2))
    a3, b3 = pf.fit_id_threshold(pd.concat([tr, extra2]))                # nearer-onset rows win
    assert (a1, b1) == pytest.approx((a3, b3))
    assert a1 > 0 and b1 > 0                                              # intensity falls with duration


def test_rint_fit_is_nan_when_threshold_unavailable():
    df = pd.DataFrame([row(rain_1h=3)])
    assert np.isnan(pf.rint_fit(df, float("nan"), float("nan"))).all()
    tiny = pd.DataFrame([row(event_id=f"e{i}") for i in range(1)])
    assert np.isnan(pf.fit_id_threshold(tiny)[0])                        # too few points -> NaN
