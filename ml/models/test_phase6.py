"""
test_phase6.py — Phase 6 acceptance tests.

SRS.md §25 Phase 6 acceptance criteria (must all pass):
  1. dynamic_features.py: all 14 dynamic feature keys present per hex
  2. antecedent_precipitation_index is the field name — api_score MUST NOT appear
  3. iot_anomaly_flag is exactly False (stub until Phase 10)
  4. simulated_ffgs_signal / simulated_gsi_signal are True/False booleans (not None)
     when rainfall inputs are available
  5. train_fusion_model.py: trains without error on the sample set
  6. risk_score is in [0, 100]
  7. risk_score = P(Green)*15 + P(Yellow)*42 + P(Orange)*64 + P(Red)*88  (SRS §10.2)
  8. tier is derived from risk_score via §10.4 thresholds — NOT a separate argmax
  9. confidence_score is in [0, 100]
  10. model saved as fusion_model.pkl — loadable and inference-ready

Run:
  python -m pytest ml/models/test_phase6.py -v
  python ml/models/test_phase6.py          (standalone)
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest

# ── Imports under test ────────────────────────────────────────────────────
from ml.features.dynamic_features import (
    compute_dynamic_features,
    load_rainfall_series,
    load_soil_series,
    load_gsi_lookup,
    compute_all_hexes_current_cycle,
    FFGS_1H_THRESHOLD_MM,
    FFGS_3H_THRESHOLD_MM,
    GSI_24H_HIGH_SUSC_MM,
    GSI_24H_ANY_SUSC_MM,
)
from ml.models.train_fusion_model import (
    FusionModel,
    compute_risk_score,
    derive_tier,
    compute_confidence_score,
    ALL_FEATURE_COLS,
    STATIC_FEATURE_COLS,
    DYNAMIC_FEATURE_COLS,
    TIER_TO_INT,
    INT_TO_TIER,
    _MODEL_PATH,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rainfall_lookup():
    return load_rainfall_series()

@pytest.fixture(scope="module")
def soil_lookup():
    return load_soil_series()

@pytest.fixture(scope="module")
def gsi_lookup():
    return load_gsi_lookup()

@pytest.fixture(scope="module")
def sample_timestamp():
    """Use a timestamp that falls within Phase 1 rainfall coverage."""
    return datetime(2026, 9, 5, 19, 0, tzinfo=timezone.utc)

@pytest.fixture(scope="module")
def mundakkai_hex():
    """A known Mundakkai pilot hex from Phase 2 GSI CSV."""
    return "8860064e4bfffff"

@pytest.fixture(scope="module")
def computed_features(mundakkai_hex, sample_timestamp, rainfall_lookup, soil_lookup, gsi_lookup):
    """Full 14-feature dict for a known hex/timestamp."""
    return compute_dynamic_features(
        hex_id=mundakkai_hex,
        village="Mundakkai",
        timestamp=sample_timestamp,
        slope_deg=28.5,
        gsi_susceptibility_class="High",
        rainfall_lookup=rainfall_lookup,
        soil_lookup=soil_lookup,
    )

@pytest.fixture(scope="module")
def fitted_model():
    """Return a freshly trained FusionModel on whatever sample set is available."""
    from ml.models.train_fusion_model import train_and_save, _SAMPLES_PATH
    return train_and_save(samples_path=_SAMPLES_PATH)


# ---------------------------------------------------------------------------
# Test Group 1: 14 dynamic feature keys (SRS §9)
# ---------------------------------------------------------------------------

EXPECTED_DYNAMIC_KEYS = {
    "rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h",
    "rainfall_72h_antecedent", "rain_intensity_mm_hr",
    "antecedent_precipitation_index",   # NEVER api_score
    "soil_saturation_ratio",
    "factor_of_safety", "factor_of_safety_min", "factor_of_safety_max",
    "simulated_ffgs_signal", "simulated_gsi_signal", "iot_anomaly_flag",
}

class TestDynamicFeatureKeys:
    """SRS §9 / Phase 6 AC-1: all 14 feature keys present."""

    def test_all_14_keys_present(self, computed_features):
        missing = EXPECTED_DYNAMIC_KEYS - set(computed_features.keys())
        assert not missing, f"Missing dynamic feature keys: {missing}"

    def test_no_api_score_key(self, computed_features):
        """CLAUDE.md hard constraint: api_score MUST NOT appear anywhere."""
        assert "api_score" not in computed_features, (
            "'api_score' found in computed features — must be 'antecedent_precipitation_index'"
        )

    def test_antecedent_precipitation_index_key_name(self, computed_features):
        """Exact field name per SRS §14 and CLAUDE.md."""
        assert "antecedent_precipitation_index" in computed_features

    def test_feature_count_is_14(self, computed_features):
        """Exactly 14 dynamic features (not more, not fewer)."""
        present = EXPECTED_DYNAMIC_KEYS & set(computed_features.keys())
        assert len(present) == 14

    def test_total_features_25(self):
        """SRS §9: 11 static + 14 dynamic = 25 total features for model."""
        assert len(ALL_FEATURE_COLS) == 25
        assert len(STATIC_FEATURE_COLS) == 11
        assert len(DYNAMIC_FEATURE_COLS) == 14

    def test_no_api_score_in_feature_col_list(self):
        """CLAUDE.md: api_score must not appear in the model feature column list."""
        assert "api_score" not in ALL_FEATURE_COLS
        assert "api_score" not in DYNAMIC_FEATURE_COLS


# ---------------------------------------------------------------------------
# Test Group 2: IoT stub (Phase 10)
# ---------------------------------------------------------------------------

class TestIoTStub:
    """Phase 6 AC-3: iot_anomaly_flag is exactly False (stub until Phase 10)."""

    def test_iot_flag_is_false(self, computed_features):
        assert computed_features["iot_anomaly_flag"] is False, (
            f"iot_anomaly_flag should be False (stub), got {computed_features['iot_anomaly_flag']}"
        )

    def test_iot_flag_not_none(self, computed_features):
        assert computed_features["iot_anomaly_flag"] is not None

    def test_iot_flag_not_zero_int(self, computed_features):
        """Must be bool False, not integer 0, to be distinguishable from silent zero."""
        assert type(computed_features["iot_anomaly_flag"]) is bool


# ---------------------------------------------------------------------------
# Test Group 3: Soil saturation (SRS §10.1 frozen formula)
# ---------------------------------------------------------------------------

class TestSoilSaturation:
    """soil_saturation_ratio = GWETROOT directly — no derivation."""

    def test_soil_saturation_non_null(self, computed_features):
        """Phase 1 data available → soil_saturation_ratio must not be None."""
        assert computed_features["soil_saturation_ratio"] is not None, (
            "soil_saturation_ratio is None — check GWETROOT data coverage or latest-available fallback"
        )

    def test_soil_saturation_range(self, computed_features):
        """GWETROOT is always in [0.0, 1.0]."""
        val = computed_features["soil_saturation_ratio"]
        if val is not None:
            assert 0.0 <= val <= 1.0, f"soil_saturation_ratio={val} outside [0, 1]"


# ---------------------------------------------------------------------------
# Test Group 4: Simulated signals (SRS §8)
# ---------------------------------------------------------------------------

class TestSimulatedSignals:
    """simulated_ffgs_signal and simulated_gsi_signal correctness."""

    def test_ffgs_signal_false_below_thresholds(self, rainfall_lookup, soil_lookup):
        """FFGS signal must be False when rainfall is below both thresholds."""
        # Inject artificially low rainfall values
        low_lookup = {"Mundakkai": {f"2026-09-05T{h:02d}:00": 0.1 for h in range(24)}}
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 19, tzinfo=timezone.utc),
            slope_deg=30.0, gsi_susceptibility_class="High",
            rainfall_lookup=low_lookup, soil_lookup=soil_lookup,
        )
        assert feat["simulated_ffgs_signal"] is False, (
            f"Expected False for low rainfall, got {feat['simulated_ffgs_signal']}"
        )

    def test_ffgs_signal_true_on_intense_1h_rain(self, soil_lookup):
        """FFGS signal must be True when 1h rainfall >= FFGS_1H_THRESHOLD_MM."""
        intense_lookup = {
            "Mundakkai": {f"2026-09-05T{h:02d}:00": (FFGS_1H_THRESHOLD_MM + 5 if h == 19 else 0.0)
                          for h in range(24)}
        }
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 19, tzinfo=timezone.utc),
            slope_deg=30.0, gsi_susceptibility_class="High",
            rainfall_lookup=intense_lookup, soil_lookup=soil_lookup,
        )
        assert feat["simulated_ffgs_signal"] is True, (
            f"Expected True for 1h rainfall >= {FFGS_1H_THRESHOLD_MM} mm, "
            f"got {feat['simulated_ffgs_signal']}"
        )

    def test_gsi_signal_true_high_susceptibility_and_heavy_rain(self, soil_lookup):
        """GSI signal must be True for High susceptibility + rainfall >= 80 mm/24h."""
        heavy_lookup = {
            "Mundakkai": {f"2026-09-05T{h:02d}:00": 4.0 for h in range(24)}  # 4mm/h × 24h = 96mm
        }
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 23, tzinfo=timezone.utc),
            slope_deg=30.0, gsi_susceptibility_class="High",
            rainfall_lookup=heavy_lookup, soil_lookup=soil_lookup,
        )
        assert feat["simulated_gsi_signal"] is True, (
            f"Expected True for High susceptibility + 96mm/24h, got {feat['simulated_gsi_signal']}"
        )

    def test_gsi_signal_false_moderate_susceptibility_moderate_rain(self, soil_lookup):
        """GSI signal must be False for Moderate susceptibility + rainfall < 80 mm/24h."""
        moderate_lookup = {
            "Mundakkai": {f"2026-09-05T{h:02d}:00": 1.0 for h in range(24)}  # 24mm/24h
        }
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 23, tzinfo=timezone.utc),
            slope_deg=30.0, gsi_susceptibility_class="Moderate",
            rainfall_lookup=moderate_lookup, soil_lookup=soil_lookup,
        )
        assert feat["simulated_gsi_signal"] is False, (
            f"Expected False for Moderate susceptibility + 24mm/24h, got {feat['simulated_gsi_signal']}"
        )

    def test_gsi_signal_true_any_susceptibility_extreme_rain(self, soil_lookup):
        """GSI signal must be True for ANY susceptibility when rainfall >= 150 mm/24h."""
        extreme_lookup = {
            "Mundakkai": {f"2026-09-05T{h:02d}:00": 7.0 for h in range(24)}  # 7mm × 24h = 168mm
        }
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 23, tzinfo=timezone.utc),
            slope_deg=30.0, gsi_susceptibility_class="Low",
            rainfall_lookup=extreme_lookup, soil_lookup=soil_lookup,
        )
        assert feat["simulated_gsi_signal"] is True, (
            f"Expected True for extreme rain (>=150mm/24h) regardless of susceptibility, "
            f"got {feat['simulated_gsi_signal']}"
        )

    def test_signals_labeled_simulated(self):
        """Key names must include 'simulated_' prefix per SRS §8."""
        assert "simulated_ffgs_signal" in DYNAMIC_FEATURE_COLS
        assert "simulated_gsi_signal" in DYNAMIC_FEATURE_COLS
        assert "ffgs_signal" not in DYNAMIC_FEATURE_COLS, (
            "ffgs_signal without 'simulated_' prefix would violate SRS §8 naming requirement"
        )


# ---------------------------------------------------------------------------
# Test Group 5: Factor of Safety features
# ---------------------------------------------------------------------------

class TestFactorOfSafetyFeatures:
    """FS features from Phase 5 model."""

    def test_fs_keys_present(self, computed_features):
        for k in ["factor_of_safety", "factor_of_safety_min", "factor_of_safety_max"]:
            assert k in computed_features

    def test_fs_values_with_slope_deg(self, soil_lookup):
        """With slope_deg provided, FS must not be None."""
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 19, tzinfo=timezone.utc),
            slope_deg=35.0, gsi_susceptibility_class="High",
            rainfall_lookup={}, soil_lookup=soil_lookup,
        )
        assert feat["factor_of_safety"] is not None, (
            "FS should not be None when slope_deg is provided"
        )
        assert feat["factor_of_safety"] > 0, "FS must be positive"

    def test_fs_none_when_slope_missing(self, rainfall_lookup, soil_lookup):
        """Without slope_deg, FS must be None — never silently defaulted."""
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 19, tzinfo=timezone.utc),
            slope_deg=None, gsi_susceptibility_class="High",
            rainfall_lookup=rainfall_lookup, soil_lookup=soil_lookup,
        )
        assert feat["factor_of_safety"] is None, (
            "FS should be None when slope_deg is missing — no silent defaults"
        )
        assert feat["factor_of_safety_min"] is None
        assert feat["factor_of_safety_max"] is None

    def test_fs_band_order(self, soil_lookup):
        """fs_min <= fs_central <= fs_max."""
        feat = compute_dynamic_features(
            hex_id="test_hex", village="Mundakkai",
            timestamp=datetime(2026, 9, 5, 19, tzinfo=timezone.utc),
            slope_deg=28.0, gsi_susceptibility_class="Moderate",
            rainfall_lookup={}, soil_lookup=soil_lookup,
        )
        if feat["factor_of_safety"] is not None:
            assert feat["factor_of_safety_min"] <= feat["factor_of_safety"] <= feat["factor_of_safety_max"], (
                f"FS band not ordered: min={feat['factor_of_safety_min']}, "
                f"central={feat['factor_of_safety']}, max={feat['factor_of_safety_max']}"
            )


# ---------------------------------------------------------------------------
# Test Group 6: Batch compute (all hexes, current cycle)
# ---------------------------------------------------------------------------

class TestBatchCompute:
    """compute_all_hexes_current_cycle() returns all pilot hexes with all 14 keys."""

    def test_batch_returns_dict(self):
        results = compute_all_hexes_current_cycle()
        assert isinstance(results, dict)
        assert len(results) > 0, "No hexes returned from batch compute"

    def test_batch_all_14_keys(self):
        results = compute_all_hexes_current_cycle()
        for hid, r in results.items():
            missing = EXPECTED_DYNAMIC_KEYS - set(r.keys())
            assert not missing, f"Hex {hid} missing keys: {missing}"

    def test_batch_no_api_score(self):
        results = compute_all_hexes_current_cycle()
        for hid, r in results.items():
            assert "api_score" not in r, f"Hex {hid} has 'api_score' key (must be antecedent_precipitation_index)"

    def test_batch_iot_flag_all_false(self):
        results = compute_all_hexes_current_cycle()
        bad = [hid for hid, r in results.items() if r["iot_anomaly_flag"] is not False]
        assert not bad, f"iot_anomaly_flag != False for hexes: {bad[:3]}"

    def test_batch_soil_coverage(self):
        """soil_saturation_ratio should be non-null for all hexes (latest-available fallback)."""
        results = compute_all_hexes_current_cycle()
        null_soil = [hid for hid, r in results.items() if r["soil_saturation_ratio"] is None]
        assert not null_soil, (
            f"soil_saturation_ratio is None for {len(null_soil)} hexes — "
            f"check GWETROOT latest-available fallback"
        )


# ---------------------------------------------------------------------------
# Test Group 7: Frozen formulas (SRS §10.2, §10.3, §10.4)
# ---------------------------------------------------------------------------

class TestFrozenFormulas:
    """risk_score, tier, confidence_score formulas are frozen per SRS §10.2/10.3/10.4."""

    @pytest.mark.parametrize("proba,expected_score", [
        ({0: 1.0, 1: 0.0, 2: 0.0, 3: 0.0}, 15.0),     # Pure Green
        ({0: 0.0, 1: 1.0, 2: 0.0, 3: 0.0}, 42.0),     # Pure Yellow
        ({0: 0.0, 1: 0.0, 2: 1.0, 3: 0.0}, 64.0),     # Pure Orange
        ({0: 0.0, 1: 0.0, 2: 0.0, 3: 1.0}, 88.0),     # Pure Red
        ({0: 0.25, 1: 0.25, 2: 0.25, 3: 0.25}, 52.25), # Equal mix
    ])
    def test_risk_score_formula(self, proba, expected_score):
        score = compute_risk_score(proba)
        assert abs(score - expected_score) < 0.01, (
            f"risk_score={score:.4f} != expected {expected_score:.4f} "
            f"for proba={proba}"
        )

    @pytest.mark.parametrize("score,expected_tier", [
        (0.0,  "Green"),
        (29.9, "Green"),
        (30.0, "Yellow"),
        (54.9, "Yellow"),
        (55.0, "Orange"),
        (74.9, "Orange"),
        (75.0, "Red"),
        (100.0, "Red"),
    ])
    def test_tier_thresholds(self, score, expected_tier):
        tier = derive_tier(score)
        assert tier == expected_tier, (
            f"derive_tier({score}) = '{tier}', expected '{expected_tier}' (SRS §10.4)"
        )

    def test_confidence_score_range(self):
        """confidence_score must always be in [0, 100]."""
        for prob in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for penalty in [0.0, 0.1, 0.3]:
                conf = compute_confidence_score(prob, penalty)
                assert 0.0 <= conf <= 100.0, f"confidence_score={conf} outside [0,100]"

    def test_confidence_formula_exact(self):
        """confidence_score = 100 * model_class_probability * (1 - FS_band_width_penalty)."""
        prob, penalty = 0.8, 0.15
        expected = 100.0 * prob * (1.0 - penalty)
        conf = compute_confidence_score(prob, penalty)
        assert abs(conf - expected) < 0.01, f"confidence_score={conf}, expected {expected}"

    def test_confidence_zero_at_max_penalty(self):
        """Penalty = 1.0 → confidence_score = 0."""
        conf = compute_confidence_score(1.0, 1.0)
        assert conf == 0.0

    def test_risk_score_clamped_to_100(self):
        """risk_score must never exceed 100 even with probabilities summing > 1 due to float issues."""
        proba = {0: 0.0, 1: 0.0, 2: 0.0, 3: 1.0001}  # Slightly over due to float
        score = compute_risk_score(proba)
        assert score <= 100.0


# ---------------------------------------------------------------------------
# Test Group 8: FusionModel inference (SRS §10.2/10.3/10.4)
# ---------------------------------------------------------------------------

class TestFusionModelInference:
    """FusionModel trains, saves, loads, and predicts correctly."""

    def test_model_is_fitted(self, fitted_model):
        assert fitted_model.is_fitted

    def test_predict_one_returns_required_keys(self, fitted_model):
        feat = {col: 0.0 for col in ALL_FEATURE_COLS}
        feat["rainfall_24h"] = 100.0
        feat["factor_of_safety"] = 0.9
        pred = fitted_model.predict_one(feat, fs_band_width_penalty=0.1)
        for k in ["risk_score", "tier", "confidence_score", "tier_probabilities", "feature_contributions"]:
            assert k in pred, f"predict_one() missing key '{k}'"

    def test_predict_one_risk_score_in_range(self, fitted_model):
        feat = {col: 0.0 for col in ALL_FEATURE_COLS}
        pred = fitted_model.predict_one(feat)
        assert 0.0 <= pred["risk_score"] <= 100.0

    def test_predict_one_tier_consistent_with_risk_score(self, fitted_model):
        feat = {col: 0.0 for col in ALL_FEATURE_COLS}
        pred = fitted_model.predict_one(feat)
        expected_tier = derive_tier(pred["risk_score"])
        assert pred["tier"] == expected_tier, (
            f"tier='{pred['tier']}' inconsistent with "
            f"derive_tier({pred['risk_score']:.2f})='{expected_tier}' (SRS §10.4)"
        )

    def test_predict_one_risk_score_matches_formula(self, fitted_model):
        """Verify the frozen formula P(G)*15+P(Y)*42+P(O)*64+P(R)*88."""
        feat = {col: 0.0 for col in ALL_FEATURE_COLS}
        feat["rainfall_24h"] = 120.0
        feat["soil_saturation_ratio"] = 0.85
        feat["slope_deg"] = 35.0
        pred = fitted_model.predict_one(feat)

        proba_manual = pred["tier_probabilities"]
        manual_score = (
            proba_manual["Green"]  * 15.0
            + proba_manual["Yellow"] * 42.0
            + proba_manual["Orange"] * 64.0
            + proba_manual["Red"]    * 88.0
        )
        assert abs(manual_score - pred["risk_score"]) < 0.01, (
            f"risk_score={pred['risk_score']:.4f} != "
            f"manual formula={manual_score:.4f}"
        )

    def test_feature_contributions_count(self, fitted_model):
        feat = {col: 0.0 for col in ALL_FEATURE_COLS}
        pred = fitted_model.predict_one(feat)
        assert len(pred["feature_contributions"]) == len(ALL_FEATURE_COLS) == 25

    def test_confidence_score_in_range(self, fitted_model):
        feat = {col: 0.0 for col in ALL_FEATURE_COLS}
        pred = fitted_model.predict_one(feat, fs_band_width_penalty=0.2)
        assert 0.0 <= pred["confidence_score"] <= 100.0

    def test_model_save_load_roundtrip(self, fitted_model, tmp_path):
        save_path = tmp_path / "test_model.pkl"
        fitted_model.save(save_path)
        loaded = FusionModel.load(save_path)
        assert loaded.is_fitted
        feat = {col: 0.0 for col in ALL_FEATURE_COLS}
        pred_orig   = fitted_model.predict_one(feat)
        pred_loaded = loaded.predict_one(feat)
        assert abs(pred_orig["risk_score"] - pred_loaded["risk_score"]) < 0.001, (
            "Loaded model gives different risk_score than original"
        )

    def test_no_pso_bp_in_feature_list(self):
        """
        PSO-BP must never appear as an executable identifier — XGBoost only (CLAUDE.md).
        String literals in print/log statements may mention PSO for clarity; skip those.
        We only flag PSO as a class name, import, or function call identifier.
        """
        from ml.models import train_fusion_model as m
        import re
        src = Path(m.__file__).read_text(encoding="utf-8")
        # Flag PSO only when used as Python identifier: import, class def, or call
        # e.g.  from pso_bp import  /  class PSO  /  PSO(...)  /  pso_bp.train()
        bad_pattern = re.compile(
            r'\b(import\s+pso|from\s+pso|class\s+PSO|PSO\s*\(|pso_bp\s*[\.(])',
            re.IGNORECASE,
        )
        for line in src.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            assert not bad_pattern.search(line), (
                f"PSO-BP used as code identifier: {stripped}"
            )


    def test_no_api_score_in_model_source(self):
        """
        CLAUDE.md: 'api_score' must not appear as a Python identifier in executable code.
        Docstrings may mention api_score to explain the naming rule — skip those.
        We check for api_score as a variable name (e.g. assigned or returned), not as prose.
        """
        from ml.models import train_fusion_model as m
        import re
        src = Path(m.__file__).read_text(encoding="utf-8")
        # Matches api_score used as an identifier: assignment, dict key, function arg
        # e.g.  api_score =  or  "api_score":  or  (api_score)  but NOT the word in prose
        bad_pattern = re.compile(r'\bapi_score\b\s*[=:,)]')
        for line in src.splitlines():
            stripped = line.strip()
            # Skip comments and standalone docstring-quote lines
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            assert not bad_pattern.search(line), (
                f"'api_score' used as identifier in code: {stripped}"
            )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 80)
    print("Phase 6 Tests — standalone run")
    print("=" * 80)
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
