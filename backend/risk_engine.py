"""
backend/risk_engine.py -- Risk-computation loop (Phase 8, SRS.md Section 10.2/10.3).

Called on each ingestion cycle:
  1. Load static features for hex from hexes.static_features JSONB
  2. Load latest dynamic features from observations
  3. Call FusionModel.predict_one() (Phase 6)
  4. Write result to risk_scores

factor_of_safety from Phase 5 is computed inside FusionModel via dynamic_features.py.
lead_time_min and data_source are now computed by Phase 9 (backend/lead_time.py).
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import get_db
from backend.lead_time import compute_lead_time
from backend.alerts.router import trigger_alert, TriggerRequest
from backend.alerts.persistent_threat import record_cycle, is_persistent_threat
from backend.alerts.gate import open_gate, check_gate
from backend.alerts.websocket_manager import broadcast_sync

# Phase 6 model
_MODEL_PATH = ROOT / "ml" / "models" / "fusion_model.pkl"

def _load_model():
    """Lazy-load FusionModel. Pre-register module so pickle resolves class correctly."""
    import sys as _sys
    import importlib
    # Must be in sys.modules BEFORE pickle.load is called
    _mod_name = "ml.models.train_fusion_model"
    if _mod_name not in _sys.modules:
        importlib.import_module(_mod_name)
    from ml.models.train_fusion_model import FusionModel
    return FusionModel.load(_MODEL_PATH)

_model_cache = None
LAST_RESULTS: dict = {}     # hex_id -> last computed result (real FS values etc.), for cached API responses

def get_model():
    """Default: the physics-first index (backend/physics_risk.py).  HYDRASENSE_RISK_MODEL=legacy selects
    the old fusion model, which returns one constant score for every hex (see physics_risk.py)."""
    global _model_cache
    import os
    if _model_cache is None and os.environ.get("HYDRASENSE_RISK_MODEL", "physics").lower() != "legacy":
        from backend.physics_risk import PhysicsRiskModel
        _model_cache = PhysicsRiskModel()
    if _model_cache is None:
        if not _MODEL_PATH.exists():
            raise FileNotFoundError(
                f"fusion_model.pkl not found at {_MODEL_PATH}. "
                "Run: python ml/models/train_fusion_model.py"
            )
        _model_cache = _load_model()
    return _model_cache


def _merge_features(static: dict, dynamic: dict) -> dict:
    """Merge static and dynamic feature dicts. Dynamic values override static."""
    merged = {}
    merged.update(static)
    merged.update(dynamic)
    return merged


def compute_and_store_risk(hex_id: str) -> dict[str, Any] | None:
    """
    Core risk-computation loop for one hex.

    Reads latest static + dynamic features, scores with FusionModel,
    writes to risk_scores, returns the result dict.
    Returns None if model not available.
    """
    try:
        model = get_model()
    except FileNotFoundError as exc:
        print(f"[risk_engine] WARNING: {exc}")
        return None

    with get_db() as conn:
        # 1. Load static features
        hex_row = conn.execute(
            "SELECT static_features FROM hexes WHERE hex_id = ?", (hex_id,)
        ).fetchone()
        static_feats: dict = {}
        if hex_row:
            try:
                static_feats = json.loads(hex_row["static_features"] or "{}")
            except (json.JSONDecodeError, TypeError):
                static_feats = {}
        else:
            try:
                from backend.onboarding.geopackage import list_onboarded_regions, get_hex_static_features
                for reg in list_onboarded_regions():
                    gfeats = get_hex_static_features(reg, hex_id)
                    if gfeats:
                        static_feats = {k: v for k, v in gfeats.items() if k != "geometry"}
                        break
            except Exception:
                pass

        # 2. Load Phase 3 dynamic rainfall & soil state
        from backend.rainfall import get_rainfall_state, get_soil_state
        try:
            import h3
            lat, lon = h3.cell_to_latlng(hex_id)
        except Exception:
            lat, lon = 11.5, 76.0  # Fallback

        rain_state = get_rainfall_state(
            hex_id=hex_id, lat=lat, lon=lon,
            elevation_m=static_feats.get("elevation_m"),
            aspect_deg=static_feats.get("aspect_deg"),
        )
        soil_state = get_soil_state(
            hex_id=hex_id, lat=lat, lon=lon,
            antecedent_precip_index=rain_state.antecedent_precipitation_index,
        )

        # 2b. Load remaining dynamic features from observations (e.g. edge FS)
        obs_row = conn.execute(
            "SELECT dynamic_features, timestamp FROM observations "
            "WHERE hex_id = ? AND COALESCE(provenance, '') != 'SIMULATED' "   # simulated rows never feed live scores
            "ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()
        dynamic_feats: dict = {}
        obs_timestamp = datetime.now(timezone.utc).isoformat()
        if obs_row:
            try:
                dynamic_feats = json.loads(obs_row["dynamic_features"] or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            obs_timestamp = obs_row["timestamp"]
            # Sensor fallback for FS if available
        else:
            # No stored observation: no dynamic features are invented.  (This branch used to inject
            # FS = 0.96 / 0.82 / 1.15 for every hex; the physics model computes FS itself.)
            dynamic_feats = {}

        # Apply Phase 3 rainfall/soil to dynamic_feats
        for k in ["rainfall_1h", "rainfall_3h", "rainfall_6h", "rainfall_24h", "rainfall_72h_antecedent", "rain_intensity_mm_hr"]:
            v = getattr(rain_state, k)
            if v is not None:
                dynamic_feats[k] = v
        
        if soil_state.soil_moisture_surface is not None:
            dynamic_feats["soil_moisture_surface"] = soil_state.soil_moisture_surface
        if soil_state.soil_saturation_ratio is not None:
            dynamic_feats["soil_saturation_ratio"] = soil_state.soil_saturation_ratio

        # 3. Merge and score
        features = _merge_features(static_feats, dynamic_feats)
        from backend.confidence import layers_from_sources
        features["_input_layers"] = layers_from_sources(
            rain_state.data_source, soil_state.source, bool(dynamic_feats.get("iot_device_id")))
        pred = model.predict_one(features)

        # 4. Build feature contributions list (top 5) -- exclude exactly-zero
        # contributions rather than padding the list with them. A feature the
        # model currently assigns zero gain to (e.g. slope_deg while Phase 3
        # terrain coverage is unavailable) is not a "top contributor," and
        # listing it as one would misrepresent a real-but-degenerate model
        # output as if every feature were meaningfully analyzed.
        contributions = pred.get("feature_contributions", {})
        top_features = sorted(
            [{"feature": k, "contribution": v} for k, v in contributions.items() if v != 0],
            key=lambda x: abs(x["contribution"]),
            reverse=True,
        )[:5]

        now_ts = datetime.now(timezone.utc).isoformat()

        # 4. Compute lead time from live/cached forecast
        features = _merge_features(static_feats, dynamic_feats)
        lead_time_min, lead_time_basis, _ = compute_lead_time(
            hex_id, features
        )
        data_source = rain_state.data_source

        # 5. Write to risk_scores
        sensor_adjusted = bool(dynamic_feats.get("iot_device_id"))
        conn.execute(
            """INSERT INTO risk_scores
               (hex_id, timestamp, risk_score, tier, confidence_score,
                lead_time_min, lead_time_basis, feature_contributions, data_source, sensor_adjusted,
                index_landslide, index_flood, rainfall_24h)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hex_id,
                now_ts,
                pred["risk_score"],
                pred["tier"],
                pred["confidence_score"],
                lead_time_min,
                lead_time_basis,
                json.dumps(top_features),
                data_source,
                int(sensor_adjusted),
                pred.get("index_landslide"),
                pred.get("index_flood"),
                dynamic_feats.get("rainfall_24h"),
            )
        )

        # FS comes from the model when it computes one, else from a stored/sensor value, else None (never a default)
        fs = pred.get("factor_of_safety", dynamic_feats.get("factor_of_safety"))
        fs_min = pred.get("factor_of_safety_min", dynamic_feats.get("factor_of_safety_min"))
        fs_max = pred.get("factor_of_safety_max", dynamic_feats.get("factor_of_safety_max"))
        fs_widened = not static_feats.get("has_local_calibration", True)

        result = {
            "hex_id":                             hex_id,
            "timestamp":                          now_ts,
            "risk_score":                         pred["risk_score"],
            "tier":                               pred["tier"],
            "confidence_score":                   pred["confidence_score"],
            "lead_time_min":                      lead_time_min,
            "lead_time_basis":                    lead_time_basis,
            "factor_of_safety":                   fs,
            "factor_of_safety_min":               fs_min,
            "factor_of_safety_max":               fs_max,
            "fs_band_widened_for_no_calibration": fs_widened,
            "top_contributing_features":          top_features,
            "data_source":                        data_source,
            "sensor_adjusted":                    sensor_adjusted,
            # kept in memory for the map (per-hazard tiers, confidence reason); not part of RiskResponse
            "index_landslide":                    pred.get("index_landslide"),
            "index_flood":                        pred.get("index_flood"),
            "confidence_primary_reason":          pred.get("confidence_primary_reason"),
            # the measured inputs this score used (null = not available; never filled in)
            "inputs": {k: dynamic_feats.get(k) for k in (
                "rainfall_1h", "rainfall_6h", "rainfall_24h", "rainfall_72h_antecedent",
                "soil_saturation_ratio")},
        }

    LAST_RESULTS[hex_id] = result

    # ── Stage 5a: Persistent Threat tracking ─────────────────────────────
    # Record this cycle BEFORE triggering alerts so is_persistent_threat() is current.
    pt_state = record_cycle(hex_id, pred["tier"])

    # ── Stage 5b: WebSocket broadcast — every cycle (not just alarms) ────
    try:
        broadcast_sync({
            "type":           "tier_change",
            "hex_id":         hex_id,
            "tier":           pred["tier"],
            "risk_score":     pred["risk_score"],
            "confidence":     pred["confidence_score"],
            "lead_time_min":  lead_time_min,
            "persistent":     pt_state.declared,
            "timestamp":      now_ts,
        })
        if pt_state.declared and pt_state.cycles == 2:   # first declaration
            broadcast_sync({
                "type":    "persist_declared",
                "hex_id":  hex_id,
                "tier":    pred["tier"],
                "cycles":  pt_state.cycles,
                "timestamp": now_ts,
            })
    except Exception as _ws_exc:
        print("[risk_engine] WARNING: WebSocket broadcast failed: %s" % _ws_exc)

    result["persistent_threat"] = pt_state.declared
    result["persist_cycles"]    = pt_state.cycles

    # 6. Phase 11 / Stage 5: CAP alert pipeline.
    # Red tier: requires Persistent Threat + two-person gate (Final.md §17.4).
    # Orange tier: fires immediately if dedup permits.
    try:
        if pred["tier"] == "Red" and pt_state.declared:
            gate_status = check_gate(hex_id)
            if gate_status not in ("APPROVED",):
                # Open (or keep) the gate PENDING — alert held until approved
                open_gate(
                    hex_id        = hex_id,
                    risk_score    = pred["risk_score"],
                    confidence    = pred["confidence_score"],
                    lead_time_min = lead_time_min,
                )
                broadcast_sync({
                    "type":       "gate_pending",
                    "hex_id":     hex_id,
                    "risk_score": pred["risk_score"],
                    "message":    "Red alert awaiting two-person gate approval",
                    "timestamp":  now_ts,
                })
                # Do NOT call trigger_alert — return early for Red pending gate
                return result
            # Gate is APPROVED — fall through to normal trigger_alert
        trigger_alert(TriggerRequest(
            hex_id           = hex_id,
            tier             = pred["tier"],
            risk_score       = pred["risk_score"],
            confidence_score = pred["confidence_score"],
            lead_time_min    = lead_time_min,
            lead_time_basis  = lead_time_basis,
        ))
    except Exception as exc:
        print("[risk_engine] WARNING: alert trigger failed for %s: %s" % (hex_id, exc))

    return result


import os  # noqa: E402


def scoring_regions() -> list[str]:
    """Region codes opted in to scoring via HYDRASENSE_SCORE_REGIONS (default: none)."""
    import os
    return [r.strip() for r in os.environ.get("HYDRASENSE_SCORE_REGIONS", "").split(",") if r.strip()]


def run_cycle_all_regions():
    """
    Run one full risk calculation cycle across all hexes in the database.
    Called by the slow loop in scheduler.py (Final.md §14.6).
    """
    regions = scoring_regions()
    cap = int(os.environ.get("HYDRASENSE_MAX_HEXES_PER_REGION", "300"))
    with get_db() as conn:
        # Legacy seeded hexes (region_code NULL / '') are always scored.  Hexes of onboarded regions are
        # scored only if listed in HYDRASENSE_SCORE_REGIONS (comma-separated region codes), because a
        # 1000+ hex region takes ~1.3 s per hex.  Each opted-in region is stride-sampled to at most `cap`
        # hexes (ordered by hex id, so the sample is spatially even and stable between cycles).
        legacy = [r["hex_id"] for r in conn.execute(
            "SELECT hex_id FROM hexes WHERE region_code IS NULL OR region_code = ''").fetchall()]
        chosen: list[str] = []
        for code in regions:
            ids = [r["hex_id"] for r in conn.execute(
                "SELECT hex_id FROM hexes WHERE region_code = ? ORDER BY hex_id", (code,)).fetchall()]
            stride = max(1, -(-len(ids) // cap))
            chosen += ids[::stride]

    hex_ids = legacy + chosen
    scored = 0
    # Scoring a hex is dominated by waiting on weather APIs (~4 s each), so hexes are scored in a few
    # parallel threads.  Kept small (default 6) to stay well inside the free API rate limits.
    workers = max(1, int(os.environ.get("HYDRASENSE_SCORE_WORKERS", "6")))

    def _one(hid):
        try:
            return bool(compute_and_store_risk(hid))
        except Exception as exc:
            print(f"[risk_engine] error scoring hex {hid}: {exc}")
            return False

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:
        scored = sum(pool.map(_one, hex_ids))
    print(f"[risk_engine] slow-cycle complete: scored {scored}/{len(hex_ids)} hexes")
    return scored
