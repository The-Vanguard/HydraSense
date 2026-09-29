"""
backend/ml.py -- Phase 5: ML Fusion Layer

Implements:
  Gap Analysis Phase 5 / v2 Section 8
  - 32-feature table schema
  - Negative sampling rules
  - Landslide and flood heads (XGBoost logic wrapper)
  - TabPFN challenger and Chronos-Bolt flags
  - Provenance gate (no SIMULATED features)

Owner: Phase 5 migration
"""
import pandas as pd
from typing import List, Optional

from backend.provenance import assert_no_simulated_in_features

# 32 Features (v2 §8.3)
FEATURE_COLUMNS = [
    # Inherited from v1 (29 - 1 - 2 = 26)
    "elevation_m", "slope_deg", "aspect_deg", "curvature", "twi", "hand_m",
    "soil_depth_default_m", "clay_percent", "sand_percent", "silt_percent", 
    "bulk_density", "organic_matter", "land_cover_class", "tree_canopy_cover",
    "antecedent_rain_3d", "antecedent_rain_7d", "antecedent_rain_15d",
    "rain_1h", "rain_3h", "rain_6h", "rain_12h", "rain_24h",
    "distance_to_stream_m", "distance_to_road_m",
    "gsi_susceptibility_class", "historical_event_count_500m",
    # New in v2 (6)
    "r_int", "p_fs_lt1", "scs_runoff_mm", "tc_min", "catchment_area_km2", "iot_soil_moisture"
]

class MLPipeline:
    def __init__(self, use_tabpfn_challenger: bool = False, use_chronos_bolt: bool = False):
        self.use_tabpfn_challenger = use_tabpfn_challenger
        self.use_chronos_bolt = use_chronos_bolt
        self.models = {}

    def validate_features(self, df: pd.DataFrame):
        """Phase 5 Gate: Provenance on every row; no SIMULATED rows."""
        # 1. Must have provenance column
        if "provenance" not in df.columns:
            raise ValueError("Feature table missing 'provenance' column.")
            
        # 2. No SIMULATED data allowed in features
        assert_no_simulated_in_features(df)
        
        # 3. Check for the 32 features
        missing = set(FEATURE_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"Missing features: {missing}")

    def generate_negative_samples(self, positive_events: pd.DataFrame, ratio: int = 5) -> pd.DataFrame:
        """
        v2 §8.4: Negative sampling rules.
        - Ratio: 5 negatives per positive
        - Spatial exclusion: >= 3 hex rings from recorded event
        - Temporal matching: same season
        """
        # (Stub for implementation)
        # In a real run, this queries the DB for non-event hexes matching criteria.
        pass
        
    def train(self, features_df: pd.DataFrame, labels_df: pd.DataFrame):
        """
        v2 §8.2: Train XGBoost models for Landslide and Flood heads separately.
        Event-grouped folds, offset T-1.
        """
        self.validate_features(features_df)
        # (Stub for XGBoost training)
        self.models['landslide_xgb'] = "xgb_ls_mock"
        self.models['flood_xgb'] = "xgb_ff_mock"
        
        if self.use_tabpfn_challenger:
            self.models['tabpfn'] = "tabpfn_mock"
            
    def predict(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """
        Predict landslide and flood risk separately, plus compound.
        """
        self.validate_features(features_df)
        
        # Output DataFrame
        out = pd.DataFrame(index=features_df.index)
        
        # (Stub for inference)
        # Mock probabilities
        out['risk_ls'] = 0.1
        out['P_class_ls'] = "Green"
        out['risk_ff'] = 0.1 
        out['P_class_ff'] = "Green"
        
        return out
