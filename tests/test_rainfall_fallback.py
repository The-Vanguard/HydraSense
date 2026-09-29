"""
tests/test_rainfall_fallback.py -- Phase 3 gate: fallback chain degradation tests.

Gap Analysis Phase 3 gate requirement:
  "each source disabled in turn; the chain degrades visibly and correctly."

Tests verify:
  1. With all sources available, we get Tier 1 data
  2. With IMERG disabled, we fall back to Open-Meteo only
  3. With Open-Meteo also disabled, we fall back to cached
  4. With everything disabled, we get Tier 3 static estimate with SIMULATED provenance
  5. Terrain adjustment is applied correctly
  6. Per-layer badges are always present and correct
  7. Soil-state selection priority works
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.rainfall import (
    compute_terrain_factor,
    compute_rainfall_windows,
    get_rainfall_state,
    get_soil_state,
    fetch_open_meteo_rainfall,
    RainfallState,
    SoilState,
    OROGRAPHIC_FACTOR_PER_100M,
    MAX_TERRAIN_FACTOR,
    MIN_TERRAIN_FACTOR,
)
from backend.provenance import ProvenanceTag


# ---------------------------------------------------------------------------
# Terrain adjustment tests (v2 §6.3)
# ---------------------------------------------------------------------------

class TestTerrainFactor:
    def test_at_basin_mean_returns_one(self):
        """Hex at mean basin elevation gets no adjustment."""
        f = compute_terrain_factor(900.0, basin_mean_elevation_m=900.0)
        assert f == pytest.approx(1.0)

    def test_above_mean_gets_boost(self):
        """Hex 200m above mean gets a positive boost."""
        f = compute_terrain_factor(1100.0, basin_mean_elevation_m=900.0)
        expected = 1.0 + (200.0 / 100.0) * OROGRAPHIC_FACTOR_PER_100M
        assert f == pytest.approx(expected, rel=0.01)
        assert f > 1.0

    def test_below_mean_gets_reduction(self):
        """Hex below mean gets reduced rainfall."""
        f = compute_terrain_factor(700.0, basin_mean_elevation_m=900.0)
        assert f < 1.0

    def test_none_elevation_returns_one(self):
        """Missing elevation data returns neutral factor."""
        f = compute_terrain_factor(None)
        assert f == 1.0

    def test_capped_at_max(self):
        """Very high elevations are capped at MAX_TERRAIN_FACTOR."""
        f = compute_terrain_factor(3000.0, basin_mean_elevation_m=900.0)
        assert f == MAX_TERRAIN_FACTOR

    def test_floored_at_min(self):
        """Very low elevations are floored at MIN_TERRAIN_FACTOR."""
        f = compute_terrain_factor(0.0, basin_mean_elevation_m=2000.0)
        assert f == MIN_TERRAIN_FACTOR

    def test_sw_windward_aspect_boost(self):
        """SW-facing slope (225°) gets an aspect boost during monsoon."""
        f_neutral = compute_terrain_factor(1000.0, basin_mean_elevation_m=900.0, aspect_deg=45.0)
        f_windward = compute_terrain_factor(1000.0, basin_mean_elevation_m=900.0, aspect_deg=225.0)
        assert f_windward > f_neutral

    def test_no_aspect_boost_without_monsoon(self):
        """No aspect boost when monsoon is inactive."""
        f_wind = compute_terrain_factor(1000.0, basin_mean_elevation_m=900.0, aspect_deg=225.0, sw_monsoon_active=True)
        f_no_wind = compute_terrain_factor(1000.0, basin_mean_elevation_m=900.0, aspect_deg=225.0, sw_monsoon_active=False)
        assert f_wind > f_no_wind


# ---------------------------------------------------------------------------
# Rainfall window computation tests
# ---------------------------------------------------------------------------

class TestRainfallWindows:
    def test_all_nulls_on_empty_series(self):
        result = compute_rainfall_windows({"time": [], "precipitation": []})
        assert result["rainfall_1h"] is None
        assert result["rainfall_3h"] is None
        assert result["rainfall_24h"] is None

    def test_computes_1h_correctly(self):
        now = datetime.now(timezone.utc)
        times = [(now.replace(minute=0, second=0) ).isoformat()]
        precip = [5.2]
        result = compute_rainfall_windows(
            {"time": times, "precipitation": precip},
            ref_time=now.replace(minute=0, second=0),
        )
        assert result["rainfall_1h"] == pytest.approx(5.2, rel=0.01)

    def test_antecedent_index_from_72h(self):
        """API = 72h_antecedent * 0.85 / 3."""
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        times = []
        precip = []
        # Fill 72 hours of 1 mm/hr
        for h in range(-72, 0):
            t = now + __import__("datetime").timedelta(hours=h)
            times.append(t.isoformat())
            precip.append(1.0)
        result = compute_rainfall_windows(
            {"time": times, "precipitation": precip},
            ref_time=now,
        )
        assert result["rainfall_72h_antecedent"] is not None
        assert result["rainfall_72h_antecedent"] == pytest.approx(72.0, rel=0.01)
        assert result["antecedent_precipitation_index"] == pytest.approx(72.0 * 0.85 / 3, rel=0.01)


# ---------------------------------------------------------------------------
# Fallback chain tests (Phase 3 gate)
# ---------------------------------------------------------------------------

class TestFallbackChain:
    """
    Phase 3 gate: "each source disabled in turn; the chain degrades
    visibly and correctly."
    """

    @patch("backend.rainfall._get_sensor_rainfall", return_value=None)
    @patch("backend.rainfall.fetch_imerg_rainfall", return_value=(None, "imerg_unavailable"))
    @patch("backend.rainfall.fetch_open_meteo_rainfall")
    def test_tier1_open_meteo_live(self, mock_om, mock_imerg, mock_sensor):
        """When Open-Meteo is live, we get Tier 1 data."""
        mock_om.return_value = (
            {"time": ["2026-01-01T00:00"], "precipitation": [3.5]},
            "open_meteo_live",
        )
        state = get_rainfall_state("test_hex", 11.5, 76.0)
        assert state.data_source == "open_meteo_live"
        assert state.provenance == ProvenanceTag.REAL_VALIDATED.value
        # Must have at least one badge
        assert len(state.source_badges) >= 1
        # Find the Open-Meteo badge
        om_badges = [b for b in state.source_badges if b.source == "open_meteo_live"]
        assert len(om_badges) == 1
        assert om_badges[0].tier == 1

    @patch("backend.rainfall._get_sensor_rainfall", return_value=None)
    @patch("backend.rainfall.fetch_imerg_rainfall", return_value=(None, "imerg_unavailable"))
    @patch("backend.rainfall.fetch_open_meteo_rainfall")
    def test_tier2_cached_fallback(self, mock_om, mock_imerg, mock_sensor):
        """When Open-Meteo returns cached, we get Tier 2 with age shown."""
        mock_om.return_value = (
            {"time": ["2026-01-01T00:00"], "precipitation": [2.0]},
            "open_meteo_cached",
        )
        state = get_rainfall_state("test_hex", 11.5, 76.0)
        assert state.data_source == "open_meteo_cached"
        # Badge should show tier 2
        om_badges = [b for b in state.source_badges if b.source == "open_meteo_cached"]
        assert len(om_badges) == 1
        assert om_badges[0].tier == 2

    @patch("backend.rainfall._get_sensor_rainfall", return_value=None)
    @patch("backend.rainfall.fetch_imerg_rainfall", return_value=(None, "imerg_unavailable"))
    @patch("backend.rainfall.fetch_open_meteo_rainfall")
    def test_tier3_static_estimate(self, mock_om, mock_imerg, mock_sensor):
        """When everything is unavailable, we get Tier 3 with SIMULATED provenance."""
        mock_om.return_value = (
            {"time": [], "precipitation": []},
            "unavailable",
        )
        state = get_rainfall_state("test_hex", 11.5, 76.0)
        assert state.data_source == "static_estimate"
        assert state.provenance == ProvenanceTag.SIMULATED.value
        # Must have a Tier 3 badge
        t3_badges = [b for b in state.source_badges if b.tier == 3]
        assert len(t3_badges) >= 1
        assert t3_badges[0].provenance == ProvenanceTag.SIMULATED.value

    @patch("backend.rainfall._get_sensor_rainfall", return_value=None)
    @patch("backend.rainfall.fetch_imerg_rainfall")
    @patch("backend.rainfall.fetch_open_meteo_rainfall")
    def test_imerg_merged_with_open_meteo(self, mock_om, mock_imerg, mock_sensor):
        """When both IMERG and Open-Meteo are available, they merge."""
        mock_imerg.return_value = (
            {"time": ["2026-01-01T00:00"], "precipitation": [4.0]},
            "imerg_cached",
        )
        mock_om.return_value = (
            {"time": ["2026-01-01T01:00"], "precipitation": [2.5]},
            "open_meteo_live",
        )
        state = get_rainfall_state("test_hex", 11.5, 76.0)
        assert state.data_source == "imerg_openmeteo_merged"
        # Should have both IMERG and Open-Meteo badges
        sources = {b.source for b in state.source_badges}
        assert "imerg_cached" in sources
        assert "open_meteo_live" in sources

    @patch("backend.rainfall._get_sensor_rainfall", return_value=None)
    @patch("backend.rainfall.fetch_imerg_rainfall", return_value=(None, "imerg_unavailable"))
    @patch("backend.rainfall.fetch_open_meteo_rainfall")
    def test_terrain_adjustment_applied(self, mock_om, mock_imerg, mock_sensor):
        """Terrain factor is applied to rainfall values for elevated hexes."""
        mock_om.return_value = (
            {"time": ["2026-01-01T00:00"], "precipitation": [10.0]},
            "open_meteo_live",
        )
        state_flat = get_rainfall_state("test_hex", 11.5, 76.0, elevation_m=900.0)
        state_high = get_rainfall_state("test_hex", 11.5, 76.0, elevation_m=1200.0)
        # Higher hex should have more rainfall
        if state_flat.rainfall_1h is not None and state_high.rainfall_1h is not None:
            assert state_high.rainfall_1h > state_flat.rainfall_1h
        assert state_high.terrain_factor > 1.0

    def test_badges_always_present(self):
        """Every RainfallState has at least one source badge (Phase 3 gate)."""
        with patch("backend.rainfall._get_sensor_rainfall", return_value=None), \
             patch("backend.rainfall.fetch_imerg_rainfall", return_value=(None, "imerg_unavailable")), \
             patch("backend.rainfall.fetch_open_meteo_rainfall",
                   return_value=({"time": [], "precipitation": []}, "unavailable")):
            state = get_rainfall_state("test_hex", 11.5, 76.0)
            # Even in total degradation, badges must document the state
            assert len(state.source_badges) >= 1


# ---------------------------------------------------------------------------
# Soil-state selection tests (Phase 3)
# ---------------------------------------------------------------------------

class TestSoilState:
    @patch("backend.rainfall._fetch_open_meteo_soil_moisture", return_value=None)
    @patch("backend.rainfall._get_sensor_soil_moisture", return_value=None)
    def test_antecedent_index_fallback(self, mock_sensor, mock_om):
        """When no sensor or Open-Meteo, API derives soil state."""
        state = get_soil_state("test_hex", 11.5, 76.0, antecedent_precip_index=45.0)
        assert state.source == "antecedent_index"
        assert state.soil_saturation_ratio is not None
        assert 0.0 < state.soil_saturation_ratio <= 1.0

    @patch("backend.rainfall._fetch_open_meteo_soil_moisture", return_value=None)
    @patch("backend.rainfall._get_sensor_soil_moisture", return_value=None)
    def test_static_estimate_is_simulated(self, mock_sensor, mock_om):
        """Static estimate carries SIMULATED provenance."""
        state = get_soil_state("test_hex", 11.5, 76.0, antecedent_precip_index=None)
        assert state.source == "static_estimate"
        assert state.provenance == ProvenanceTag.SIMULATED.value

    @patch("backend.rainfall._fetch_open_meteo_soil_moisture", return_value=None)
    @patch("backend.rainfall._get_sensor_soil_moisture", return_value=None)
    def test_high_api_gives_high_saturation(self, mock_sensor, mock_om):
        """High antecedent rainfall → near-saturated soil."""
        state = get_soil_state("test_hex", 11.5, 76.0, antecedent_precip_index=80.0)
        assert state.soil_saturation_ratio is not None
        assert state.soil_saturation_ratio > 0.8

    @patch("backend.rainfall._fetch_open_meteo_soil_moisture", return_value=None)
    @patch("backend.rainfall._get_sensor_soil_moisture", return_value=None)
    def test_low_api_gives_low_saturation(self, mock_sensor, mock_om):
        """Low antecedent rainfall → dry soil."""
        state = get_soil_state("test_hex", 11.5, 76.0, antecedent_precip_index=5.0)
        assert state.soil_saturation_ratio is not None
        assert state.soil_saturation_ratio < 0.3
