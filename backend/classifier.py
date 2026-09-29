"""
backend/classifier.py -- Phase 5: Trigger-Type Classifier

Implements:
  Gap Analysis Phase 5 / v2 Section 7.5
  - Rule-based Trigger-type classifier (CLOUDBURST_FLASH, SATURATION_FLOOD,
    SATURATION_LANDSLIDE, LANDSLIDE_DAM, COMPOUND_CASCADE, UNSPECIFIED).

Owner: Phase 5 migration
"""

def classify_trigger(
    r_int: float,
    m: float,
    flood_indicator: float,
    r_acc: float,
    flood_head_level: str, # "Green", "Yellow", "Orange", "Red"
    p_fs_lt1: float,
    landslide_head_level: str,
    rain_persisting: bool,
    blockage_suspect: bool
) -> str:
    """
    Classify the dominant mechanism using v2 rules (Section 7.5).
    """
    is_flood_orange_red = flood_head_level in ("Orange", "Red")
    is_ls_orange_red = landslide_head_level in ("Orange", "Red")
    
    # 1. LANDSLIDE_DAM
    # "E4 flag -> Evacuate downstream of the blocked reach; expect delayed surge"
    if blockage_suspect:
        return "LANDSLIDE_DAM"
        
    # Check for SATURATION_LANDSLIDE (used in compound rule)
    is_saturation_landslide = (
        m >= 0.7 and 
        (p_fs_lt1 > 0.5 or is_ls_orange_red) and 
        rain_persisting
    )
    
    # 2. COMPOUND_CASCADE
    # "SATURATION_LANDSLIDE and flood head >= Orange in the same or downstream catchment"
    if is_saturation_landslide and is_flood_orange_red:
        return "COMPOUND_CASCADE"
        
    # 3. SATURATION_LANDSLIDE
    # "m >= 0.7 and (P(FS<1) high or landslide head >= Orange) and rain persisting"
    if is_saturation_landslide:
        return "SATURATION_LANDSLIDE"
        
    # 4. SATURATION_FLOOD
    # "r_acc >= 1 and m >= 0.7 and flood head >= Orange"
    if r_acc >= 1.0 and m >= 0.7 and is_flood_orange_red:
        return "SATURATION_FLOOD"
        
    # 5. CLOUDBURST_FLASH
    # "R_int >= 1 on a short window and soil not yet saturated (m < 0.7) and flood indicator high"
    if r_int >= 1.0 and m < 0.7 and flood_indicator > 0.5:
        return "CLOUDBURST_FLASH"
        
    # 6. UNSPECIFIED
    return "UNSPECIFIED"
