"""
tests/test_phase5_ml.py

Tests Phase 5 (Trigger-type classifier and ML feature constraints)
"""
import sys
import pandas as pd
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.classifier import classify_trigger
from backend.ml import MLPipeline, FEATURE_COLUMNS
from backend.provenance import ProvenanceTag

def test_trigger_classifier_rules():
    """Test the trigger classifier logic correctly assigns mechanisms."""
    
    # 1. LANDSLIDE_DAM (blockage_suspect = True)
    assert classify_trigger(
        r_int=0.5, m=0.8, flood_indicator=0.2, r_acc=0.5,
        flood_head_level="Green", p_fs_lt1=0.1, landslide_head_level="Green",
        rain_persisting=False, blockage_suspect=True
    ) == "LANDSLIDE_DAM"
    
    # 2. CLOUDBURST_FLASH 
    # r_int >= 1, m < 0.7, flood_indicator > 0.5
    assert classify_trigger(
        r_int=1.2, m=0.5, flood_indicator=0.8, r_acc=0.1,
        flood_head_level="Green", p_fs_lt1=0.1, landslide_head_level="Green",
        rain_persisting=True, blockage_suspect=False
    ) == "CLOUDBURST_FLASH"
    
    # 3. SATURATION_FLOOD
    # r_acc >= 1, m >= 0.7, flood >= Orange
    assert classify_trigger(
        r_int=0.5, m=0.9, flood_indicator=0.6, r_acc=1.5,
        flood_head_level="Orange", p_fs_lt1=0.1, landslide_head_level="Green",
        rain_persisting=True, blockage_suspect=False
    ) == "SATURATION_FLOOD"
    
    # 4. SATURATION_LANDSLIDE
    # m >= 0.7, p_fs_lt1 high or LS >= Orange, rain_persisting
    assert classify_trigger(
        r_int=0.5, m=0.9, flood_indicator=0.1, r_acc=0.5,
        flood_head_level="Green", p_fs_lt1=0.8, landslide_head_level="Green",
        rain_persisting=True, blockage_suspect=False
    ) == "SATURATION_LANDSLIDE"
    
    # 5. COMPOUND_CASCADE
    # SATURATION_LANDSLIDE AND flood >= Orange
    assert classify_trigger(
        r_int=0.5, m=0.9, flood_indicator=0.6, r_acc=0.5,
        flood_head_level="Red", p_fs_lt1=0.8, landslide_head_level="Orange",
        rain_persisting=True, blockage_suspect=False
    ) == "COMPOUND_CASCADE"
    
    # 6. UNSPECIFIED (fallback)
    assert classify_trigger(
        r_int=0.5, m=0.5, flood_indicator=0.1, r_acc=0.1,
        flood_head_level="Green", p_fs_lt1=0.1, landslide_head_level="Green",
        rain_persisting=False, blockage_suspect=False
    ) == "UNSPECIFIED"

def test_ml_provenance_gate():
    """Verify that the ML pipeline rejects SIMULATED rows and requires all features."""
    pipeline = MLPipeline()
    
    # Create valid dummy features
    valid_data = {col: [0.0] for col in FEATURE_COLUMNS}
    valid_data["provenance"] = [ProvenanceTag.REAL_VALIDATED.value]
    
    df_valid = pd.DataFrame(valid_data)
    
    # Should not raise
    pipeline.validate_features(df_valid)
    
    # Add a SIMULATED row -> should raise ValueError (from assert_no_simulated_in_features)
    invalid_data = valid_data.copy()
    invalid_data["provenance"] = [ProvenanceTag.SIMULATED.value]
    df_invalid = pd.DataFrame(invalid_data)
    
    with pytest.raises(RuntimeError, match="SIMULATED"):
        pipeline.validate_features(df_invalid)
        
    # Missing columns -> should raise ValueError
    df_missing = df_valid.drop(columns=["r_int"])
    with pytest.raises(ValueError, match="Missing features"):
        pipeline.validate_features(df_missing)
