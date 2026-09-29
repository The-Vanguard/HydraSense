"""
backend/models.py -- Pydantic request/response models for all SRS.md Section 15 endpoints.

Field names are FROZEN per SRS.md Section 14/15 -- do not rename without team flag.
"""

from __future__ import annotations
from typing import Any, List, Optional
from pydantic import BaseModel, Field
from backend.provenance import ProvenanceTag  # Gap Analysis §0.2 — provenance policy


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
    hex_id:                             str
    timestamp:                          str
    risk_score:                         float
    tier:                               str
    confidence_score:                   float
    lead_time_min:                      Optional[int] = None
    lead_time_basis:                    str = "forecast_projection"
    # None = not available. These used to default to 0.96 / 0.82 / 1.15 for every hex, i.e. made-up values.
    factor_of_safety:                   Optional[float] = None
    factor_of_safety_min:               Optional[float] = None
    factor_of_safety_max:               Optional[float] = None
    fs_band_widened_for_no_calibration: bool = False
    top_contributing_features:          List[dict] = Field(default_factory=list)
    data_source:                        Any = "live"
    # v2 provenance field (Gap Analysis §0.2) — REAL_VALIDATED | REAL_RECONSTRUCTED | SIMULATED
    provenance:                         Optional[ProvenanceTag] = None

class RiskMapEntry(BaseModel):
    hex_id:                             str
    risk_score:                         float
    tier:                               str
    confidence_score:                   Optional[float] = None      # was 85.0: an invented default
    lead_time_min:                      Optional[int] = None
    data_source:                        Any = "live"
    flood_tier:                         Optional[str] = None
    landslide_tier:                     Optional[str] = None
    has_local_calibration:              bool = False                # was True: an optimistic default
    fs_band_widened_for_no_calibration: bool = False
    instrumented_hex:                   bool = False
    village:                            Optional[str] = None
    lat:                                Optional[float] = None
    lng:                                Optional[float] = None
    region_code:                        Optional[str] = "wayanad-kl"
    region_label:                       Optional[str] = "Wayanad"
    state:                              Optional[str] = "Kerala"
    district:                           Optional[str] = "Wayanad"
    # v2 provenance field (Gap Analysis §0.2) — drives UI badge in hydrasense-theme.css
    # Values: REAL_VALIDATED | REAL_RECONSTRUCTED | SIMULATED
    # SIMULATED rows must show the page-wide simulated banner (Gap Analysis §0.4.4)
    provenance:                         Optional[ProvenanceTag] = None
    # v2 confidence fields for UI desaturation and reason line (Gap Analysis §0.4.2)
    conf_reason:                        Optional[str] = None   # "no_local_calibration" | "wide_fs_band" | None
    sensor_adjusted:                    bool = False           # True when a real sensor overrode the gridded value

class RiskHistoryEntry(BaseModel):
    timestamp:  str
    risk_score: float
    tier:       str

class UncertaintyResponse(BaseModel):
    hex_id:              str
    factor_of_safety:     Optional[float] = None
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
    # v2 provenance fields (Gap Analysis §0.3) ────────────────────────────
    # provenance: one of REAL_VALIDATED | REAL_RECONSTRUCTED | SIMULATED
    # grade:      A (agency-validated) | B (two sources agree) | C (single/conflicting)
    # time_uncertainty_h: if > few hours, the -3h and -1h samples are excluded
    # sources_used: list of source citations used to reconstruct this record
    provenance:                 Optional[ProvenanceTag] = None
    grade:                      Optional[str] = None           # "A" | "B" | "C"
    time_uncertainty_h:         Optional[float] = None         # hours
    position_uncertainty_m:     Optional[float] = None         # metres
    sources_used:               Optional[List[str]] = None     # citation list
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
    chronos_forecast_low_m:      Optional[List[float]] = None
    chronos_forecast_high_m:     Optional[List[float]] = None
    chronos_prediction_length_steps: Optional[int] = None
    chronos_caveat:         Optional[str] = None
    # Real Phase 5 factor-of-safety (SRS §10.1) computed from this point's
    # real slope + the region's latest real soil reading -- see
    # factor_of_safety_note for what it is/isn't (never this historical
    # event's own at-disaster soil conditions).
    factor_of_safety:       Optional[float] = None
    factor_of_safety_min:   Optional[float] = None
    factor_of_safety_max:   Optional[float] = None
    factor_of_safety_note:  Optional[str] = None


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
