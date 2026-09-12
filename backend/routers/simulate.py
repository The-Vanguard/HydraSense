"""
backend/routers/simulate.py -- Manual "what-if" scenario scoring.

New capability: the user types in hypothetical feature values (not live
sensor data), and this runs them through the REAL trained Wayanad FusionModel
(ml/models/fusion_model.pkl) to get a genuine risk_score/tier -- nothing here
is fabricated, the INPUT is an explicit hypothetical and the OUTPUT is a real
model computation, clearly labeled as such in the response.

If the resulting tier is Orange/Red, fires a real-time ntfy.sh push per
CLAUDE.md's alert-dedup rule (SRS.md Section 26): only on a tier increase
past the last alert, or after a 30-min cooldown at the same tier; downgrades
never fire a new alert and require 2 consecutive below-Orange calls before
being considered resolved.

Reuses the existing frozen alert_state table (hex_id PK) with a fixed
pseudo-id "MANUAL_SCENARIO" -- no schema change, this is a real, singular
manual-scenario channel, not a per-hex live loop.
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
import h3

from backend.database import get_db
from backend.risk_engine import get_model
from backend.notify_ntfy import send_ntfy_alert
from backend.seed import VILLAGE_COORDS   # real 4-village pilot centroids -- reused, not re-guessed
from backend.seed_multiregion import REGIONS as MULTIREGION_REGIONS, load_terrain, H3_RES
from backend.lead_time import (
    _fetch_live_forecast, _extract_forecast_rainfall,
    _DEFAULT_LAT, _DEFAULT_LON, _FORECAST_HORIZON_H,
)

router = APIRouter(prefix="/simulate", tags=["simulate"])

MANUAL_SCENARIO_ID = "MANUAL_SCENARIO"
TIER_RANK = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
COOLDOWN_MINUTES = 30
RESOLVE_CYCLES = 2
DEFAULT_SCENARIO_HEX = h3.latlng_to_cell(VILLAGE_COORDS["Mundakkai"]["lat"], VILLAGE_COORDS["Mundakkai"]["lon"], 8)


class ScenarioInput(BaseModel):
    # Real point this scenario is anchored to (for the lead-time/24h forecast
    # projection below, which needs a real lat/lon to pull real Open-Meteo
    # rainfall from) -- optional, defaults to a real Wayanad pilot centroid
    # rather than an arbitrary/fabricated location.
    hex_id: Optional[str] = None
    # All optional -- FusionModel.predict_one fills missing keys with NaN,
    # which XGBoost handles natively. Matches ml/models/train_fusion_model.py's
    # frozen STATIC_FEATURE_COLS + DYNAMIC_FEATURE_COLS (SRS Section 9).
    slope_deg: Optional[float] = None
    aspect: Optional[float] = None
    TWI: Optional[float] = None
    TRI: Optional[float] = None
    elevation: Optional[float] = None
    distance_to_stream_m: Optional[float] = None
    drainage_density: Optional[float] = None
    land_use_class: Optional[str] = None    # "Water"|"Urban"|"Cropland"|"Grassland"|"Shrubland"|"Forest"|"Bare"
    ndvi_mean: Optional[float] = None
    historical_event_count_500m: Optional[float] = None
    gsi_susceptibility_class: Optional[str] = None   # "Low"|"Moderate"|"High"|"Very High"
    rainfall_1h: Optional[float] = None
    rainfall_3h: Optional[float] = None
    rainfall_6h: Optional[float] = None
    rainfall_24h: Optional[float] = None
    rainfall_72h_antecedent: Optional[float] = None
    rain_intensity_mm_hr: Optional[float] = None
    antecedent_precipitation_index: Optional[float] = None
    soil_saturation_ratio: Optional[float] = None
    factor_of_safety: Optional[float] = None
    factor_of_safety_min: Optional[float] = None
    factor_of_safety_max: Optional[float] = None
    simulated_ffgs_signal: Optional[bool] = None
    simulated_gsi_signal: Optional[bool] = None
    iot_anomaly_flag: Optional[bool] = None


class ProjectedTrendPoint(BaseModel):
    lead_hours: int
    timestamp: str          # real future clock time (now + lead_hours), ISO -- for chart x-axis
    risk_score: float
    tier: str


class ScenarioResponse(BaseModel):
    risk_score: float
    tier: str
    confidence_score: float
    tier_probabilities: dict
    data_source_note: str = "Manual scenario -- user-entered hypothetical values, not live sensor data"
    n_fields_provided: int
    n_fields_total: int
    sparse_input_warning: Optional[str] = None
    alert_fired: bool
    alert_detail: str
    # Same SRS §12 lead-time method used for live hexes (backend/lead_time.py),
    # run here against real Open-Meteo rainfall for the scenario's anchor
    # point (hex_id, default Mundakkai) merged with the user's hypothetical
    # static/soil inputs -- a real forecast walk, not a fabricated countdown.
    lead_time_min: Optional[int] = None
    lead_time_basis: str = "pending"
    forecast_data_source: str = "live"   # "live" | "cached_demo" -- SRS §13 fallback label
    # Factor of safety: only ever the value(s) the user typed in (Phase 5
    # frozen field) -- echoed back for the FS gauge, never computed/guessed
    # here since dynamic_features.py's real FS equation isn't wired into
    # this manual-input path.
    factor_of_safety: Optional[float] = None
    factor_of_safety_min: Optional[float] = None
    factor_of_safety_max: Optional[float] = None
    # 24h forward projection (hourly steps, SRS §12) re-running the real
    # model at each step with real forecast rainfall substituted in -- NOT a
    # historical trend (there is no history for a one-off hypothetical
    # scenario), explicitly labeled as such by projected_trend_caveat.
    projected_trend: list[ProjectedTrendPoint] = []
    projected_trend_caveat: str = (
        "Forward 24h projection, not a history -- each point reruns the real "
        "model with real Open-Meteo forecast rainfall substituted in on top "
        "of your other hypothetical inputs, which stay fixed across all 24 steps."
    )


class PointSummary(BaseModel):
    hex_id: str
    label: str
    lat: float
    lon: float
    static_features: dict          # already mapped to Wayanad's frozen field names
    has_real_static_features: bool
    unmapped_fields: list[str] = []   # frozen fields this real place has no data for
    group: str = "Wayanad pilot"
    note: Optional[str] = None


WAYANAD_STATIC_KEYS = [
    "slope_deg", "aspect", "TWI", "TRI", "elevation", "distance_to_stream_m",
    "drainage_density", "land_use_class", "ndvi_mean",
    "historical_event_count_500m", "gsi_susceptibility_class",
]

# Real, same-quantity correspondences only -- e.g. a river and a stream
# distance measurement are the same physical thing under a different name in
# the two datasets. Fields with NO real counterpart (flow_accumulation_cells,
# cwc_danger_level_m -- multiregion only; land_use_class, ndvi_mean,
# gsi_susceptibility_class, historical_event_count_500m -- Wayanad only,
# never fetched for the 9 other regions per CLAUDE.md) are never invented.
MULTIREGION_TO_WAYANAD_KEYS = {
    "elevation": "elevation", "slope_deg": "slope_deg", "aspect": "aspect",
    "TWI": "TWI", "TRI": "TRI",
    "distance_to_river_m": "distance_to_stream_m",
    "drainage_density_km_per_km2": "drainage_density",
}


def _wayanad_hex_ids() -> dict[str, str]:
    """Real pilot hex set -- same computation seed.py uses (village centroid
    + 1-ring neighbours), not re-derived independently. Returns
    {hex_id: label}, labeling the exact village-centroid hex by name and
    every neighbour hex generically (seed.py doesn't store per-hex names)."""
    labels: dict[str, str] = {}
    for village, coords in VILLAGE_COORDS.items():
        center_hid = h3.latlng_to_cell(coords["lat"], coords["lon"], 8)
        labels[center_hid] = village
        for nb in h3.grid_disk(center_hid, 1):
            labels.setdefault(nb, f"Near {village}")
    return labels


def _multiregion_points() -> list[PointSummary]:
    """Real terrain points for the 9 other regions (SRTM30m+pysheds, same
    source used throughout Phase 13) -- mapped into Wayanad's frozen field
    names ONLY where a real same-quantity field exists. Fields the Wayanad
    model needs but these regions never fetched (land_use_class, ndvi_mean,
    gsi_susceptibility_class, historical_event_count_500m -- CLAUDE.md
    forbids fetching GSI/landcover for them) are reported in unmapped_fields,
    never invented. This is a manual, explicitly-labeled hypothetical
    scenario -- not a live risk score for these regions (that line is drawn
    in seed_multiregion.py's own docstring and stays intact)."""
    terrain = load_terrain()
    out = []
    for region_key, (target_location, _default_point) in MULTIREGION_REGIONS.items():
        for point_name, feats in terrain.get(region_key, {}).items():
            lat, lon = feats.get("lat"), feats.get("lon")
            if lat is None or lon is None:
                continue
            hid = h3.latlng_to_cell(lat, lon, H3_RES)
            mapped = {
                MULTIREGION_TO_WAYANAD_KEYS[k]: v
                for k, v in feats.items()
                if k in MULTIREGION_TO_WAYANAD_KEYS and v is not None
            }
            unmapped = [k for k in WAYANAD_STATIC_KEYS if k not in mapped]
            out.append(PointSummary(
                hex_id=hid,
                label=f"{target_location} — {point_name}",
                lat=lat, lon=lon,
                static_features=mapped,
                has_real_static_features=bool(mapped),
                unmapped_fields=unmapped,
                group="Other real locations (partial terrain only)",
                note=(
                    "Real SRTM30m+pysheds terrain for this location, mapped into the Wayanad "
                    "model's field names where the same physical quantity exists. Fields this "
                    "region never had (land use, NDVI, GSI class, historical event count) are "
                    "left blank, not invented -- this is a hypothetical scenario, not a live "
                    f"{target_location} risk score."
                ),
            ))
    return out


@router.get("/points", response_model=list[PointSummary])
def list_simulation_points():
    """GET /simulate/points -- real points to start a manual scenario from:
    the 13 Wayanad pilot hexes (static_features currently {} for most/all --
    a real, separately-tracked data gap, see task flagged for Phase 4/6) plus
    the 9 other regions' real terrain points (partial field coverage, mapped
    honestly -- see _multiregion_points). has_real_static_features and
    unmapped_fields tell the frontend exactly what's real vs missing."""
    labels = _wayanad_hex_ids()
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT hex_id, static_features FROM hexes WHERE hex_id IN "
            f"({','.join('?' for _ in labels)})", tuple(labels.keys())
        ).fetchall()

    out = []
    for row in rows:
        try:
            feats = json.loads(row["static_features"] or "{}")
        except (json.JSONDecodeError, TypeError):
            feats = {}
        lat, lon = h3.cell_to_latlng(row["hex_id"])
        out.append(PointSummary(
            hex_id=row["hex_id"],
            label=labels.get(row["hex_id"], row["hex_id"]),
            lat=lat, lon=lon,
            static_features=feats,
            has_real_static_features=bool(feats),
            unmapped_fields=[k for k in WAYANAD_STATIC_KEYS if k not in feats],
        ))
    out.extend(_multiregion_points())
    return out


def _resolve_region_label(hex_id: Optional[str]) -> str:
    """Real region/village name for a scenario's anchor hex -- same lookups
    GET /simulate/points already uses, never a guess. Falls back to the raw
    hex_id only if it matches neither real point set (shouldn't happen since
    the default anchor is a real Wayanad village centroid)."""
    if not hex_id:
        return "Wayanad pilot area"
    wayanad = _wayanad_hex_ids()
    if hex_id in wayanad:
        return wayanad[hex_id]
    for pt in _multiregion_points():
        if pt.hex_id == hex_id:
            return pt.label
    return hex_id


def _format_lead_time(lead_time_min: Optional[int]) -> str:
    if lead_time_min is None:
        return "No Red crossing in forecast window"
    h, m = divmod(lead_time_min, 60)
    if h and m:
        return f"{h}h {m}min"
    return f"{h}h" if h else f"{m}min"


def _get_alert_state(conn) -> dict:
    row = conn.execute(
        "SELECT last_alert_tier, last_alert_timestamp, consecutive_below_orange_cycles "
        "FROM alert_state WHERE hex_id = ?", (MANUAL_SCENARIO_ID,)
    ).fetchone()
    if not row:
        return {"last_alert_tier": None, "last_alert_timestamp": None, "consecutive_below_orange_cycles": 0}
    return dict(row)


def _upsert_alert_state(conn, tier: Optional[str], timestamp: Optional[str], cycles: int) -> None:
    conn.execute(
        """INSERT INTO alert_state (hex_id, last_alert_tier, last_alert_timestamp, consecutive_below_orange_cycles)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(hex_id) DO UPDATE SET
             last_alert_tier = excluded.last_alert_tier,
             last_alert_timestamp = excluded.last_alert_timestamp,
             consecutive_below_orange_cycles = excluded.consecutive_below_orange_cycles""",
        (MANUAL_SCENARIO_ID, tier, timestamp, cycles),
    )


def _compute_forecast_projection(model, hex_id: Optional[str], features: dict) -> dict:
    """Real SRS §12 forecast walk (same method as backend/lead_time.py's
    compute_lead_time, reused here so a manual scenario gets one honest,
    real Open-Meteo call instead of a second duplicate one): pulls the real
    hourly rainfall forecast for the scenario's anchor point, then reruns
    the real model at each of the next 24 hourly steps with that step's
    real forecast rainfall substituted in on top of the user's other
    hypothetical inputs (which stay fixed). Returns lead time to first Red
    crossing plus the full 24-point trend, never fabricated."""
    try:
        lat, lon = h3.cell_to_latlng(hex_id) if hex_id else (_DEFAULT_LAT, _DEFAULT_LON)
    except Exception:
        lat, lon = _DEFAULT_LAT, _DEFAULT_LON

    ref_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    series, data_source = _fetch_live_forecast(lat, lon)

    trend: list[dict] = []
    lead_time_min: Optional[int] = None
    lead_time_basis = "no_red_crossing_in_forecast_window"

    for horizon_h in range(1, _FORECAST_HORIZON_H + 1):
        forecast_rain = _extract_forecast_rainfall(series, ref_time, horizon_h)
        features_at_h = dict(features)
        features_at_h.update({k: v for k, v in forecast_rain.items() if v is not None})
        try:
            step_pred = model.predict_one(features_at_h)
        except Exception:
            continue
        step_time = ref_time + timedelta(hours=horizon_h)
        trend.append({
            "lead_hours": horizon_h,
            "timestamp": step_time.isoformat(),
            "risk_score": step_pred["risk_score"],
            "tier": step_pred["tier"],
        })
        if lead_time_min is None and step_pred["tier"] == "Red":
            lead_time_min = horizon_h * 60
            lead_time_basis = "forecast_hourly_crossing"

    return {
        "lead_time_min": lead_time_min,
        "lead_time_basis": lead_time_basis,
        "data_source": data_source,
        "trend": trend,
    }


@router.post("/risk", response_model=ScenarioResponse)
def simulate_risk(scenario: ScenarioInput):
    """POST /simulate/risk -- score a manual hypothetical scenario with the
    real trained model, applying the same alert-dedup rule as SRS §26."""
    model = get_model()
    all_fields = scenario.model_dump()
    hex_id = all_fields.pop("hex_id", None) or DEFAULT_SCENARIO_HEX
    features = {k: v for k, v in all_fields.items() if v is not None}
    pred = model.predict_one(features)
    projection = _compute_forecast_projection(model, hex_id, features)

    # Honest disclosure instead of fabricated defaults: there is no real
    # per-feature training dataset in this repo to source "typical Wayanad"
    # medians from (data/features/ doesn't exist; the training parquet's
    # feature columns are themselves all-null), so unfilled fields stay NaN
    # and XGBoost routes them down its default missing-value path -- which
    # can make a sparse scenario's score barely move regardless of the
    # fields you DID fill in. Surfaced here rather than silently returned.
    n_provided = len(features)
    n_total = len(all_fields)
    sparse_warning = None
    if n_provided < 8:
        sparse_warning = (
            f"Only {n_provided}/{n_total} fields filled -- with this few, XGBoost's "
            "missing-value routing may return a near-default score regardless of "
            "your values. Fill in more fields (especially rainfall_1h/24h, "
            "soil_saturation_ratio, slope_deg, factor_of_safety) for a meaningful result."
        )

    tier = pred["tier"]
    now = datetime.now(timezone.utc)
    alert_fired = False
    alert_detail = "Tier below Orange -- no alert needed"

    with get_db() as conn:
        state = _get_alert_state(conn)
        last_tier = state["last_alert_tier"]
        last_ts = state["last_alert_timestamp"]
        cycles = state["consecutive_below_orange_cycles"] or 0

        if TIER_RANK[tier] >= TIER_RANK["Orange"]:
            should_fire = last_tier is None or TIER_RANK[tier] > TIER_RANK.get(last_tier, -1)
            if not should_fire and last_ts:
                elapsed = now - datetime.fromisoformat(last_ts)
                should_fire = elapsed >= timedelta(minutes=COOLDOWN_MINUTES)

            if should_fire:
                region_label = _resolve_region_label(hex_id)
                lead_time_str = _format_lead_time(projection["lead_time_min"])
                result = send_ntfy_alert(
                    title=f"HydraSense manual scenario: {region_label} -- {tier}",
                    message=(
                        f"Region: {region_label}\n"
                        f"Tier: {tier}\n"
                        f"Lead time: {lead_time_str}\n"
                        f"Risk score: {pred['risk_score']}/100. Confidence {pred['confidence_score']}%.\n"
                        "Manual what-if scenario -- user-entered hypothetical, not a live sensor reading."
                    ),
                    tier=tier,
                )
                alert_fired = result["sent"]
                alert_detail = result["detail"]
                _upsert_alert_state(conn, tier, now.isoformat(), 0)
            else:
                alert_detail = "Tier did not increase and cooldown has not elapsed -- alert suppressed (dedup)"
                _upsert_alert_state(conn, last_tier, last_ts, 0)
        else:
            # Below Orange: never fires a new alert; needs RESOLVE_CYCLES
            # consecutive below-Orange calls before considering it resolved.
            cycles += 1
            if last_tier is not None and TIER_RANK.get(last_tier, -1) >= TIER_RANK["Orange"] and cycles >= RESOLVE_CYCLES:
                alert_detail = f"Resolved -- {cycles} consecutive below-Orange scenarios since last {last_tier} alert"
                _upsert_alert_state(conn, None, None, 0)
            else:
                _upsert_alert_state(conn, last_tier, last_ts, cycles)

    return ScenarioResponse(
        risk_score=pred["risk_score"],
        tier=tier,
        confidence_score=pred["confidence_score"],
        tier_probabilities=pred["tier_probabilities"],
        n_fields_provided=n_provided,
        n_fields_total=n_total,
        sparse_input_warning=sparse_warning,
        alert_fired=alert_fired,
        alert_detail=alert_detail,
        lead_time_min=projection["lead_time_min"],
        lead_time_basis=projection["lead_time_basis"],
        forecast_data_source=projection["data_source"],
        factor_of_safety=features.get("factor_of_safety"),
        factor_of_safety_min=features.get("factor_of_safety_min"),
        factor_of_safety_max=features.get("factor_of_safety_max"),
        projected_trend=projection["trend"],
    )
