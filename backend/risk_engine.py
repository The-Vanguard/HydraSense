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

def get_model():
    global _model_cache
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

        # 2. Load latest dynamic features
        obs_row = conn.execute(
            "SELECT dynamic_features, timestamp FROM observations "
            "WHERE hex_id = ? ORDER BY timestamp DESC LIMIT 1",
            (hex_id,)
        ).fetchone()
        dynamic_feats: dict = {}
        obs_timestamp = datetime.now(timezone.utc).isoformat()
        if obs_row:
            try:
                dynamic_feats = json.loads(obs_row["dynamic_features"] or "{}")
            except (json.JSONDecodeError, TypeError):
                dynamic_feats = {}
            obs_timestamp = obs_row["timestamp"]

        # 3. Merge and score
        features = _merge_features(static_feats, dynamic_feats)
        pred = model.predict_one(features)

        # 4. Build feature contributions list (top 5)
        contributions = pred.get("feature_contributions", {})
        top_features = sorted(
            [{"feature": k, "contribution": v} for k, v in contributions.items()],
            key=lambda x: abs(x["contribution"]),
            reverse=True,
        )[:5]

        now_ts = datetime.now(timezone.utc).isoformat()

        # 4. Phase 9: compute lead time + data_source from live/cached forecast
        features = _merge_features(static_feats, dynamic_feats)
        lead_time_min, lead_time_basis, data_source = compute_lead_time(
            hex_id, features
        )

        # 5. Write to risk_scores
        conn.execute(
            """INSERT INTO risk_scores
               (hex_id, timestamp, risk_score, tier, confidence_score,
                lead_time_min, lead_time_basis, feature_contributions, data_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            )
        )

        return {
            "hex_id":                    hex_id,
            "timestamp":                 now_ts,
            "risk_score":                pred["risk_score"],
            "tier":                      pred["tier"],
            "confidence_score":          pred["confidence_score"],
            "lead_time_min":             lead_time_min,
            "lead_time_basis":           lead_time_basis,
            "top_contributing_features": top_features,
            "data_source":               data_source,
        }
