"""
backend/models.py -- Pydantic request/response models for all SRS.md Section 15 endpoints.

Field names are FROZEN per SRS.md Section 14/15 -- do not rename without team flag.
"""

from __future__ import annotations
from typing import Any, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ingestion request bodies (SRS.md Section 15)
# ---------------------------------------------------------------------------

class RainfallIngest(BaseModel):
    hex_id:    Optional[str]   = None
    lat:       Optional[float] = None
    lon:       Optional[float] = None
    timestamp: str
    value_mm:  float

class RainfallForecastIngest(BaseModel):
    hex_id:          Optional[str]   = None
    lat:             Optional[float] = None
    lon:             Optional[float] = None
    forecast_series: List[dict]      # [{timestamp, value_mm}, ...]

class SoilMoistureIngest(BaseModel):
    hex_id:    Optional[str]   = None
    lat:       Optional[float] = None
    lon:       Optional[float] = None
    timestamp: str
    value_pct: float

class IoTIngest(BaseModel):
    device_id:   str
    hex_id:      str
    timestamp:   str
    sensor_type: str   # "rainfall" | "soil_moisture" | "tilt"
    value:       float
    battery:     float


# ---------------------------------------------------------------------------
# Risk response (SRS.md Section 15 -- GET /risk/{hex_id})
# ---------------------------------------------------------------------------

class RiskResponse(BaseModel):
    hex_id:                  str
    timestamp:               str
    risk_score:              float
    tier:                    str
    confidence_score:        float
    lead_time_min:           Optional[int]   = None   # null until Phase 9
    lead_time_basis:         str             = "pending_phase_9"
    top_contributing_features: List[dict]   = Field(default_factory=list)
    data_source:             str             = "live"  # "live" | "cached_demo"

class RiskMapEntry(BaseModel):
    hex_id:     str
    risk_score: float
    tier:       str
    data_source: str = "live"

class RiskHistoryEntry(BaseModel):
    timestamp:  str
    risk_score: float
    tier:       str

class UncertaintyResponse(BaseModel):
    hex_id:              str
    factor_of_safety_min: Optional[float]
    factor_of_safety_max: Optional[float]
    confidence_score:    float
    band_note:           str = ""


# ---------------------------------------------------------------------------
# Historical event map response (GET /events/map -- multiregion dataset,
# Phase 13). Sourced historical events, NOT a live model output -- see
# data_source_note.
# ---------------------------------------------------------------------------

class EventMapEntry(BaseModel):
    event_id:             str
    hex_id:                Optional[str] = None
    region:                Optional[str] = None
    lat:                   Optional[float] = None
    lon:                    Optional[float] = None
    date:                   Optional[str] = None
    type:                   Optional[str] = None
    severity:               Optional[str] = None
    source:                 Optional[str] = None
    coordinate_precision:   str = "village-level"
    data_source_note:       str = "Historical event, sourced -- not a live model output"
    # Real SRTM30m+pysheds terrain, from hexes.static_features -- same for
    # every event at this hex.
    static_features:       Optional[dict] = None
    # Real TabPFN-computed score for THIS specific historical event's actual
    # at-event conditions (Step 6a, run_tabpfn_inference.py) -- not a live
    # score, and only present for events that had a flash_flood/landslide
    # positive snapshot in the training data. tabpfn_caveat is always shown
    # alongside the score per CLAUDE.md's labeling rule -- never hide it.
    tabpfn_risk_score:      Optional[float] = None
    tabpfn_tier:            Optional[str] = None
    tabpfn_caveat:          Optional[str] = None
    # Real Chronos-Bolt zero-shot forecast (Step 6b), continuing from the
    # nearest real GUARDIAN river station's last real observed reading --
    # NOT a live forecast for the current moment (see chronos_caveat).
    chronos_station:        Optional[str] = None
    chronos_last_observed_time:  Optional[str] = None
    chronos_last_observed_value_m: Optional[float] = None
    chronos_forecast_median_m:   Optional[List[float]] = None
    chronos_caveat:         Optional[str] = None


# ---------------------------------------------------------------------------
# LOEO validation response (SRS.md Section 15 -- GET /validation/loeo)
# ---------------------------------------------------------------------------

class LoeoSummaryResponse(BaseModel):
    loeo_n_events:       int
    loeo_n_detected:     int
    detection_rate:      float
    false_positive_rate: Optional[float]
    timing_error:        dict
    data_completeness_note: str
    run_timestamp_utc:   str


# ---------------------------------------------------------------------------
# Shelter response (SRS.md Section 15 -- GET /shelters/nearest/{hex_id})
# ---------------------------------------------------------------------------

class ShelterResponse(BaseModel):
    shelter_id:    str
    name:          str
    hex_id:        Optional[str]
    lat:           float
    lon:           float
    distance_km:   float
