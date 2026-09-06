"""
backend/routers/ingest.py -- SRS.md Section 15 ingestion endpoints.

POST /ingest/rainfall
POST /ingest/rainfall_forecast
POST /ingest/soil_moisture
POST /ingest/iot

Each write to observations, then triggers risk-computation loop for that hex.
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import APIRouter, HTTPException
from backend.database import get_db
from backend.models import RainfallIngest, RainfallForecastIngest, SoilMoistureIngest, IoTIngest
from backend.risk_engine import compute_and_store_risk

import h3

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _resolve_hex(hex_id: str | None, lat: float | None, lon: float | None) -> str:
    """Return hex_id from explicit id or lat/lon -> H3 res-8 cell."""
    if hex_id:
        return hex_id
    if lat is not None and lon is not None:
        return h3.latlng_to_cell(lat, lon, 8)
    raise HTTPException(status_code=422, detail="Provide either hex_id or lat+lon")


def _store_observation(hex_id: str, timestamp: str, new_fields: dict) -> None:
    """Upsert dynamic_features for this hex+timestamp observation."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, dynamic_features FROM observations "
            "WHERE hex_id=? AND timestamp=? LIMIT 1",
            (hex_id, timestamp)
        ).fetchone()
        if row:
            existing = json.loads(row["dynamic_features"] or "{}")
            existing.update(new_fields)
            conn.execute(
                "UPDATE observations SET dynamic_features=? WHERE id=?",
                (json.dumps(existing), row["id"])
            )
        else:
            conn.execute(
                "INSERT INTO observations (hex_id, timestamp, dynamic_features) VALUES (?,?,?)",
                (hex_id, timestamp, json.dumps(new_fields))
            )


@router.post("/rainfall", status_code=202)
def ingest_rainfall(body: RainfallIngest):
    """
    POST /ingest/rainfall  { hex_id | lat, lon, timestamp, value_mm }
    Stores observation, triggers risk recomputation.
    """
    hid = _resolve_hex(body.hex_id, body.lat, body.lon)
    _store_observation(hid, body.timestamp, {"rainfall_1h": body.value_mm})
    result = compute_and_store_risk(hid)
    return {"accepted": True, "hex_id": hid, "risk_preview": result}


@router.post("/rainfall_forecast", status_code=202)
def ingest_rainfall_forecast(body: RainfallForecastIngest):
    """
    POST /ingest/rainfall_forecast  { hex_id | lat, lon, forecast_series }
    Stores forecast series for lead-time computation (Phase 9 reads this).
    """
    hid = _resolve_hex(body.hex_id, body.lat, body.lon)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO observations (hex_id, timestamp, dynamic_features) VALUES (?,?,?)",
            (
                hid,
                datetime.now(timezone.utc).isoformat(),
                json.dumps({"forecast_series": body.forecast_series}),
            )
        )
    return {"accepted": True, "hex_id": hid, "forecast_steps": len(body.forecast_series)}


@router.post("/soil_moisture", status_code=202)
def ingest_soil_moisture(body: SoilMoistureIngest):
    """
    POST /ingest/soil_moisture  { hex_id | lat, lon, timestamp, value_pct }
    value_pct is stored as soil_saturation_ratio (0-1).
    """
    hid = _resolve_hex(body.hex_id, body.lat, body.lon)
    # Normalise pct -> ratio if value looks like a percentage (>1)
    ratio = body.value_pct / 100.0 if body.value_pct > 1.0 else body.value_pct
    _store_observation(hid, body.timestamp, {"soil_saturation_ratio": ratio})
    result = compute_and_store_risk(hid)
    return {"accepted": True, "hex_id": hid, "risk_preview": result}


@router.post("/iot", status_code=202)
def ingest_iot(body: IoTIngest):
    """
    POST /ingest/iot  { device_id, hex_id, timestamp, sensor_type, value, battery }
    Persists per-hex sensor state for iot_anomaly_flag (Phase 10 reads this).
    """
    VALID_SENSOR_TYPES = {"rainfall", "soil_moisture", "tilt"}
    if body.sensor_type not in VALID_SENSOR_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"sensor_type must be one of {VALID_SENSOR_TYPES}"
        )

    # Map sensor value to the appropriate dynamic feature key
    feature_map = {
        "rainfall":      "rainfall_1h",
        "soil_moisture": "soil_saturation_ratio",
        "tilt":          "tilt_value",
    }
    value = body.value
    if body.sensor_type == "soil_moisture" and value > 1.0:
        value = value / 100.0  # normalise pct -> ratio

    _store_observation(body.hex_id, body.timestamp, {
        feature_map[body.sensor_type]: value,
        "iot_device_id":   body.device_id,
        "iot_battery":     body.battery,
        "iot_sensor_type": body.sensor_type,
        "iot_anomaly_flag": False,   # Phase 10 sets this when sensor goes offline
    })

    # Persist sensor last-seen state (Phase 10 uses this for dropout detection)
    _persist_sensor_state(body.hex_id, body.device_id, body.sensor_type, body.timestamp)

    result = compute_and_store_risk(body.hex_id)
    return {"accepted": True, "hex_id": body.hex_id, "device_id": body.device_id,
            "risk_preview": result}


def _persist_sensor_state(hex_id: str, device_id: str, sensor_type: str, timestamp: str) -> None:
    """
    Store per-hex sensor state so Phase 10 / Phase 6 can read iot_anomaly_flag.
    Written to data/iot/sensor_state.json keyed by hex_id.
    This is the storage interface agreed for Phase 10 coordination.
    """
    import pathlib
    state_path = ROOT / "data" / "iot" / "sensor_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        existing = {}
    existing[hex_id] = {
        "device_id":      device_id,
        "sensor_type":    sensor_type,
        "last_seen_utc":  timestamp,
        "anomaly_flag":   False,
    }
    state_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
