"""
simulator.py — IoT MQTT publisher replaying a scripted escalation curve.

Implements: SRS.md Section 16 (IoT Simulation Spec), Phase 10.
Owner: Dev B (Phase 10)

WHAT THIS IS:
  A pure software simulation — no real hardware, no LoRaWAN, no real sensors.
  Publishes synthetic MQTT messages for the pilot H3 hexes, replaying the
  5-stage escalation curve from SRS.md Section 20's demo script so the demo
  is reproducible and rehearsable.

TOPICS PUBLISHED (per SRS.md Section 16):
  sensors/{hex_id}/rainfall      — mm/hr intensity reading
  sensors/{hex_id}/soil_moisture — fractional proxy (0.0–1.0, labeled simulated)
  sensors/{hex_id}/tilt          — degrees deviation from baseline

ESCALATION STAGES (SRS.md Section 20 demo script, frozen):
  Stage 1 — Normal:              baseline readings, Green tier expected
  Stage 2 — Rainfall rising:     synthetic rain spike begins, Yellow expected
  Stage 3 — Saturation building: soil moisture + antecedent rain both high, Orange expected
  Stage 4 — Slope response:      FS drops below 1.0 on adjacent hexes, Red expected
  Stage 5 — Decision:            CAP alert fires; simulator holds Red readings

SENSOR DROPOUT (SRS.md Section 16, frozen wording):
  At the start of Stage 3, one device stops publishing.
  The backend (Phase 8 POST /ingest/iot) and Phase 6 feature engine detect the
  dropout and label that hex as "external-data-only estimate" — NEVER "satellite-only".
  The dashboard (Phase 12) must show this label per SRS.md Section 16.

BACKEND WIRING:
  Publishes to MQTT broker (default: localhost:1883, configurable via env vars).
  Also POSTs to Phase 8's POST /ingest/iot endpoint over HTTP for backends
  that aren't running an MQTT subscriber yet — both paths are active by default.
  The HTTP path is the fallback; MQTT is primary.

HARD CONSTRAINTS (CLAUDE.md):
  - No real hardware or LoRaWAN integration.
  - "external-data-only estimate" — not "satellite-only" (SRS.md Section 16, frozen).
  - All sensor values MUST be labeled SIMULATED in JSON payloads (data_source field).
  - Timeout on backend HTTP posts: 3 seconds (fail loudly, don't block the sim).
"""

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Optional imports — degrade gracefully if not installed
# ---------------------------------------------------------------------------
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print(
        "WARNING: paho-mqtt not installed. MQTT publishing disabled.\n"
        "  pip install paho-mqtt==1.6.1\n"
        "  HTTP POST to backend will still work if BACKEND_URL is set.",
        file=sys.stderr,
    )

try:
    import httpx
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False
    print(
        "WARNING: httpx not installed. HTTP backend posting disabled.\n"
        "  pip install httpx",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# Pilot cluster hexes — generated from Phase 2's gsi_susceptibility.csv.
# These are the H3 res-8 hex IDs for the 4 pilot villages.
# Must match what Phase 2/3 put in the hexes table.
# ---------------------------------------------------------------------------
# Village core hexes (Moderate susceptibility — SRS.md Section 2)
HEX_MUNDAKKAI_CORE    = "8860064e4bfffff"   # Mundakkai + Chooralmala centroid (shared at res-8)
HEX_ATTAMALA_CORE     = "8860064e41fffff"   # Attamala centroid
HEX_PUNJIRIMATTOM_CORE = "88600640b7fffff"  # Punjirimattom centroid

# High-susceptibility adjacent hexes (inner ring — used for slope-response stage)
HEX_ADJACENT_1 = "88600640b5fffff"  # Mundakkai inner-slope
HEX_ADJACENT_2 = "8860064e43fffff"  # Mundakkai inner-slope

# All pilot hexes receiving sensor readings
ALL_PILOT_HEXES = [
    HEX_MUNDAKKAI_CORE,
    HEX_ATTAMALA_CORE,
    HEX_PUNJIRIMATTOM_CORE,
    HEX_ADJACENT_1,
    HEX_ADJACENT_2,
]

# ---------------------------------------------------------------------------
# Device assignments — one simulated device per hex for primary readings.
# device_id format: SIM_{HEX_SHORT}_{SENSOR_TYPE}
# The "dropout" device is DEVICE_DROPOUT — it goes offline at Stage 3.
# ---------------------------------------------------------------------------
def _dev(hex_id: str, sensor: str) -> str:
    return f"SIM_{hex_id[:8]}_{sensor}"

DEVICE_DROPOUT_HEX = HEX_ADJACENT_1   # The hex whose sensor goes offline at Stage 3
DEVICE_DROPOUT_ID  = _dev(DEVICE_DROPOUT_HEX, "rainfall")

# ---------------------------------------------------------------------------
# Configuration (from env vars, with documented defaults)
# ---------------------------------------------------------------------------
MQTT_HOST     = os.environ.get("MQTT_HOST",     "localhost")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

# Phase 8 backend ingestion endpoint
BACKEND_URL     = os.environ.get("BACKEND_URL", "http://localhost:8000")
INGEST_ENDPOINT = f"{BACKEND_URL}/ingest/iot"
HTTP_TIMEOUT    = 3.0   # seconds — fail loudly if backend slow, don't block sim

# Inter-message interval within a stage (seconds)
TICK_INTERVAL = float(os.environ.get("TICK_INTERVAL_SEC", "2.0"))

# Ticks per stage (controls how long each stage lasts)
TICKS_PER_STAGE = int(os.environ.get("TICKS_PER_STAGE", "8"))

# ---------------------------------------------------------------------------
# Escalation curve definition (SRS.md Section 20, frozen)
# Each stage defines sensor values for each hex.
# All values are SIMULATED — never presented as real sensor data.
# ---------------------------------------------------------------------------

@dataclass
class SensorReading:
    """Simulated sensor reading for one hex at one stage."""
    hex_id:        str
    device_id:     str
    sensor_type:   str      # "rainfall" | "soil_moisture" | "tilt"
    value:         float
    unit:          str
    battery:       float    # 0.0–1.0 battery proxy (simulated)
    # REQUIRED label per CLAUDE.md / SRS.md Section 16
    data_source:   str = "SIMULATED — not a real sensor"
    offline:       bool = False


@dataclass
class StageSpec:
    """One stage of the SRS.md Section 20 escalation curve."""
    stage_number:  int
    name:          str
    description:   str
    expected_tier: str
    expected_risk: int
    # Per-hex, per-sensor target values: {hex_id: {sensor_type: value}}
    readings:      dict = field(default_factory=dict)
    # Dropout: if True, DEVICE_DROPOUT_ID stops publishing from the start of this stage onward.
    # The runtime tracks dropout state via a local variable in run_simulation() — this field
    # is only used to signal the *transition* point (Stage 3), not the ongoing state.
    dropout_starts: bool = False


# Stage 1 — Normal: baseline readings, Green expected (risk ~21)
STAGE_1 = StageSpec(
    stage_number  = 1,
    name          = "Normal",
    description   = "Baseline readings — no hazard signal",
    expected_tier = "Green",
    expected_risk = 21,
    readings = {
        HEX_MUNDAKKAI_CORE:    {"rainfall": 0.2,  "soil_moisture": 0.35, "tilt": 0.1},
        HEX_ATTAMALA_CORE:     {"rainfall": 0.1,  "soil_moisture": 0.32, "tilt": 0.0},
        HEX_PUNJIRIMATTOM_CORE:{"rainfall": 0.2,  "soil_moisture": 0.30, "tilt": 0.1},
        HEX_ADJACENT_1:        {"rainfall": 0.2,  "soil_moisture": 0.34, "tilt": 0.0},
        HEX_ADJACENT_2:        {"rainfall": 0.1,  "soil_moisture": 0.33, "tilt": 0.0},
    },
)

# Stage 2 — Rainfall rising: synthetic rain spike begins, Yellow expected (risk ~48)
STAGE_2 = StageSpec(
    stage_number  = 2,
    name          = "Rainfall rising",
    description   = "Synthetic rain spike begins — antecedent_precipitation_index climbing",
    expected_tier = "Yellow",
    expected_risk = 48,
    readings = {
        HEX_MUNDAKKAI_CORE:    {"rainfall": 18.5, "soil_moisture": 0.52, "tilt": 0.2},
        HEX_ATTAMALA_CORE:     {"rainfall": 16.0, "soil_moisture": 0.50, "tilt": 0.1},
        HEX_PUNJIRIMATTOM_CORE:{"rainfall": 17.0, "soil_moisture": 0.48, "tilt": 0.2},
        HEX_ADJACENT_1:        {"rainfall": 19.0, "soil_moisture": 0.55, "tilt": 0.3},
        HEX_ADJACENT_2:        {"rainfall": 17.5, "soil_moisture": 0.51, "tilt": 0.2},
    },
)

# Stage 3 — Saturation building: soil moisture + antecedent rain both high, Orange (~67)
# DROPOUT STARTS HERE: DEVICE_DROPOUT_ID goes offline at Stage 3, tick 1.
STAGE_3 = StageSpec(
    stage_number  = 3,
    name          = "Saturation building",
    description   = "soil_moisture + antecedent rain both high — Orange imminent",
    expected_tier = "Orange",
    expected_risk = 67,
    dropout_starts = True,   # DEVICE_DROPOUT_ID stops publishing from this stage onward
    readings = {
        HEX_MUNDAKKAI_CORE:    {"rainfall": 34.0, "soil_moisture": 0.78, "tilt": 0.5},
        HEX_ATTAMALA_CORE:     {"rainfall": 31.0, "soil_moisture": 0.76, "tilt": 0.3},
        HEX_PUNJIRIMATTOM_CORE:{"rainfall": 32.0, "soil_moisture": 0.74, "tilt": 0.4},
        # HEX_ADJACENT_1 sensor is now OFFLINE — no reading published for it
        HEX_ADJACENT_2:        {"rainfall": 33.0, "soil_moisture": 0.77, "tilt": 0.5},
    },
)

# Stage 4 — Slope response: FS drops below 1.0 on adjacent hexes, Red expected (risk ~82)
# Dropout is still active (started at Stage 3) — tracked by run_simulation()'s local variable.
STAGE_4 = StageSpec(
    stage_number  = 4,
    name          = "Slope response",
    description   = "FS drops below 1.0 (band 0.7-1.1) — Red, feature-contribution panel shows",
    expected_tier = "Red",
    expected_risk = 82,
    readings = {
        HEX_MUNDAKKAI_CORE:    {"rainfall": 52.0, "soil_moisture": 0.91, "tilt": 1.2},
        HEX_ATTAMALA_CORE:     {"rainfall": 48.0, "soil_moisture": 0.89, "tilt": 0.8},
        HEX_PUNJIRIMATTOM_CORE:{"rainfall": 50.0, "soil_moisture": 0.87, "tilt": 0.9},
        # HEX_ADJACENT_1 still offline
        HEX_ADJACENT_2:        {"rainfall": 55.0, "soil_moisture": 0.92, "tilt": 1.8},
    },
)

# Stage 5 — Decision: CAP alert fires; hold Red readings
# Dropout still active — tracked by run_simulation()'s local variable.
STAGE_5 = StageSpec(
    stage_number  = 5,
    name          = "Decision",
    description   = "CAP alert fires on screen — tier, score, confidence, lead time, shelter shown",
    expected_tier = "Red",
    expected_risk = 82,    # same values as Stage 4 (system in alarm state)
    readings = STAGE_4.readings,   # identical sensor values — backend holds Red
)

ESCALATION_CURVE = [STAGE_1, STAGE_2, STAGE_3, STAGE_4, STAGE_5]


# ---------------------------------------------------------------------------
# MQTT client setup
# ---------------------------------------------------------------------------

def build_mqtt_client() -> Optional[object]:
    """
    Build and connect an MQTT client.
    Returns None if paho-mqtt not installed or broker unreachable.
    Never raises — always degrades gracefully (CLAUDE.md).

    Uses CallbackAPIVersion.VERSION2 (paho-mqtt 2.x requirement).
    """
    if not MQTT_AVAILABLE:
        return None

    try:
        # paho-mqtt 2.x: must specify CallbackAPIVersion to avoid DeprecationWarning
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"hydrasense-iot-sim-{uuid.uuid4().hex[:8]}",
        )
    except AttributeError:
        # Fallback for paho-mqtt 1.x (older installs)
        client = mqtt.Client(client_id=f"hydrasense-iot-sim-{uuid.uuid4().hex[:8]}")

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
        print(f"[iot-sim] MQTT connected: {MQTT_HOST}:{MQTT_PORT}")
        return client
    except Exception as e:
        print(
            f"WARNING: [iot-sim] MQTT connect failed: {e}\n"
            "  Continuing without MQTT — HTTP POST only.",
            file=sys.stderr,
        )
        return None


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def build_payload(reading: SensorReading, stage: StageSpec) -> dict:
    """
    Build the POST /ingest/iot payload per SRS.md Section 15 API contract.

    Schema (Section 15):
      POST /ingest/iot { device_id, hex_id, timestamp, sensor_type, value, battery }

    Additional fields included for traceability:
      data_source: "SIMULATED — not a real sensor" (REQUIRED, SRS.md Section 16)
      stage_name:  current demo stage label
      offline:     True if this is an "offline" heartbeat (should not appear normally)
    """
    return {
        "device_id":   reading.device_id,
        "hex_id":      reading.hex_id,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "sensor_type": reading.sensor_type,
        "value":       reading.value,
        "battery":     reading.battery,
        # REQUIRED label — SRS.md Section 16 / CLAUDE.md
        "data_source": reading.data_source,
        "stage_name":  stage.name,
    }


def make_readings_for_stage(stage: StageSpec, dropout_active: bool) -> list[SensorReading]:
    """
    Generate the full set of SensorReadings for a given stage.

    If dropout_active: HEX_ADJACENT_1 has no readings (device is offline).
    The backend detects the dropout via timestamp staleness and falls back to
    'external-data-only estimate' label for that hex (SRS.md Section 16).
    """
    readings: list[SensorReading] = []
    battery_proxy = max(0.3, 1.0 - (stage.stage_number - 1) * 0.08)

    for hex_id, sensors in stage.readings.items():
        if dropout_active and hex_id == DEVICE_DROPOUT_HEX:
            # Device is offline — do NOT publish for this hex.
            # The absence of messages IS the dropout signal.
            continue

        for sensor_type, value in sensors.items():
            readings.append(SensorReading(
                hex_id      = hex_id,
                device_id   = _dev(hex_id, sensor_type),
                sensor_type = sensor_type,
                value       = value,
                unit        = _unit(sensor_type),
                battery     = battery_proxy,
            ))
    return readings


def _unit(sensor_type: str) -> str:
    return {"rainfall": "mm/hr", "soil_moisture": "fraction_0_1", "tilt": "degrees"}[sensor_type]


# ---------------------------------------------------------------------------
# Publish helpers
# ---------------------------------------------------------------------------

def publish_mqtt(client, reading: SensorReading, stage: StageSpec) -> None:
    """Publish one reading to MQTT. Silent on failure (MQTT is best-effort)."""
    if not client:
        return
    topic   = f"sensors/{reading.hex_id}/{reading.sensor_type}"
    payload = json.dumps(build_payload(reading, stage))
    try:
        result = client.publish(topic, payload, qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"  [iot-sim] MQTT publish error on {topic}: rc={result.rc}", file=sys.stderr)
    except Exception as e:
        print(f"  [iot-sim] MQTT publish exception: {e}", file=sys.stderr)


def post_to_backend(reading: SensorReading, stage: StageSpec) -> None:
    """
    POST sensor reading to Phase 8's /ingest/iot endpoint.
    Timeout: 3 seconds — fail loudly but don't block the simulation.
    Per CLAUDE.md: any external call needs a timeout + visible failure.
    """
    if not HTTP_AVAILABLE:
        return
    payload = build_payload(reading, stage)
    try:
        response = httpx.post(INGEST_ENDPOINT, json=payload, timeout=HTTP_TIMEOUT)
        if response.status_code not in (200, 201, 204):
            print(
                f"  [iot-sim] Backend POST {response.status_code}: "
                f"{INGEST_ENDPOINT} — {response.text[:120]}",
                file=sys.stderr,
            )
    except httpx.TimeoutException:
        print(
            f"  [iot-sim] Backend POST timeout ({HTTP_TIMEOUT}s): {INGEST_ENDPOINT}\n"
            "  Simulation continues — backend may not be running yet.",
            file=sys.stderr,
        )
    except httpx.RequestError as e:
        print(
            f"  [iot-sim] Backend POST error: {e}\n"
            "  Check BACKEND_URL env var. Simulation continues.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------

def run_simulation(dry_run: bool = False) -> None:
    """
    Run the full 5-stage escalation simulation.

    dry_run: if True, prints payloads without publishing (for testing).
    """
    print()
    print("=" * 65)
    print("HydraSense IoT Simulator — SRS.md Section 16 + 20")
    print("=" * 65)
    print(f"  Pilot hexes:    {len(ALL_PILOT_HEXES)}")
    print(f"  Stages:         {len(ESCALATION_CURVE)}")
    print(f"  Ticks/stage:    {TICKS_PER_STAGE}")
    print(f"  Tick interval:  {TICK_INTERVAL}s")
    print(f"  MQTT broker:    {MQTT_HOST}:{MQTT_PORT}")
    print(f"  Backend URL:    {BACKEND_URL}")
    print(f"  Dropout hex:    {DEVICE_DROPOUT_HEX} (offline from Stage 3)")
    print(f"  Dry run:        {dry_run}")
    print()
    print("  NOTE: ALL SENSOR VALUES ARE SIMULATED (SRS.md Section 16).")
    print("  The 'external-data-only estimate' label appears on the dashboard")
    print("  for the dropout hex — per SRS.md Section 16 frozen wording.")
    print("  NEVER 'satellite-only' or 'NWP-only'.")
    print("=" * 65)
    print()

    mqtt_client = None if dry_run else build_mqtt_client()

    dropout_active = False   # flips True at start of Stage 3

    for stage in ESCALATION_CURVE:
        # Handle dropout transition
        if stage.dropout_starts and not dropout_active:
            dropout_active = True
            print(
                f"\n  *** SENSOR DROPOUT: device '{DEVICE_DROPOUT_ID}' going OFFLINE ***\n"
                f"      Hex {DEVICE_DROPOUT_HEX} will fall back to\n"
                f"      'external-data-only estimate' (SRS.md Sec 16)\n"
                f"      Backend detects dropout via timestamp staleness.\n"
            )

        print(
            f"[Stage {stage.stage_number}] {stage.name.upper()}\n"
            f"  {stage.description}\n"
            f"  Expected: Tier={stage.expected_tier}, Risk={stage.expected_risk}"
        )

        for tick in range(1, TICKS_PER_STAGE + 1):
            readings = make_readings_for_stage(stage, dropout_active)

            for reading in readings:
                if dry_run:
                    payload = build_payload(reading, stage)
                    print(
                        f"  [DRY-RUN] {reading.hex_id[:12]}.. "
                        f"{reading.sensor_type:14s} = {reading.value:6.1f} {reading.unit}"
                    )
                else:
                    publish_mqtt(mqtt_client, reading, stage)
                    post_to_backend(reading, stage)

            if not dry_run:
                print(
                    f"  tick {tick:02d}/{TICKS_PER_STAGE} — "
                    f"{len(readings)} readings published "
                    f"{'(dropout active)' if dropout_active else ''}"
                )
            time.sleep(TICK_INTERVAL if not dry_run else 0)

        print()

    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("[iot-sim] MQTT disconnected.")

    print("=" * 65)
    print("[iot-sim] Simulation complete — all 5 stages replayed.")
    print()
    print("  Dropout hex was OFFLINE from Stage 3 onward:")
    print(f"    {DEVICE_DROPOUT_HEX} (device: {DEVICE_DROPOUT_ID})")
    print("  Dashboard should show 'external-data-only estimate' for that hex.")
    print("  (SRS.md Section 16 frozen label — verify in Phase 12 frontend)")
    print("=" * 65)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="HydraSense IoT simulator — SRS.md Section 16 / Phase 10"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without publishing to MQTT or backend",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=TICKS_PER_STAGE,
        help=f"Ticks per stage (default: {TICKS_PER_STAGE})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=TICK_INTERVAL,
        help=f"Seconds between ticks (default: {TICK_INTERVAL})",
    )
    parser.add_argument(
        "--stage",
        type=int,
        default=None,
        help="Run only a specific stage (1–5) — useful for per-stage testing",
    )
    args = parser.parse_args()

    # Override globals from CLI args
    TICKS_PER_STAGE = args.ticks
    TICK_INTERVAL   = args.interval

    if args.stage is not None:
        if args.stage < 1 or args.stage > 5:
            print("ERROR: --stage must be between 1 and 5", file=sys.stderr)
            sys.exit(1)
        stage = ESCALATION_CURVE[args.stage - 1]
        dropout = args.stage >= 3
        # Print the same simulation disclaimer as the full run, so per-stage testing
        # is never mistaken for real sensor data (SRS.md Section 16 / CLAUDE.md).
        print()
        print("=" * 65)
        print(f"[iot-sim] Single-stage mode — Stage {args.stage}: {stage.name}")
        print(f"  Expected: Tier={stage.expected_tier}, Risk={stage.expected_risk}")
        print(f"  Dropout active: {dropout} (hex {DEVICE_DROPOUT_HEX})")
        print(f"  Dry run:        {args.dry_run}")
        print()
        print("  NOTE: ALL SENSOR VALUES ARE SIMULATED (SRS.md Section 16).")
        print("  data_source='SIMULATED — not a real sensor' on every payload.")
        print("=" * 65)
        print()
        mqtt_client = None if args.dry_run else build_mqtt_client()
        for tick in range(1, TICKS_PER_STAGE + 1):
            readings = make_readings_for_stage(stage, dropout_active=dropout)
            for r in readings:
                if args.dry_run:
                    print(f"  {r.hex_id[:12]}.. {r.sensor_type:14s} = {r.value:.1f}")
                else:
                    publish_mqtt(mqtt_client, r, stage)
                    post_to_backend(r, stage)
            time.sleep(TICK_INTERVAL if not args.dry_run else 0)
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
    else:
        run_simulation(dry_run=args.dry_run)
