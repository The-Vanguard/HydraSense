"""
tests/test_provenance_leakage.py
CI leakage test — Gap Analysis §0.2 rule 5.

GATE: This test file MUST pass on every push before merge.
      A SIMULATED row in the feature table is a build-breaking failure.

What this test checks:
  1. The ProvenanceTag enum has exactly the three canonical values.
  2. validate_tag() correctly accepts valid tags and rejects unknown ones.
  3. assert_no_simulated_in_features() raises on SIMULATED rows and on a
     missing provenance column, and passes silently on real data.
  4. (Requires DB) No risk_scores row that has a tier (i.e. was actually scored)
     also has a NULL provenance — all scored rows must be tagged.
  5. (Requires DB) All historical_events rows have a provenance tag after
     migration. Pre-migration NULL rows are flagged so they can be graded.
  6. provenance_for_source() maps source descriptor strings correctly.
  7. is_science_allowed() correctly gatekeeps which tags enter training.

Run with:
  pytest tests/test_provenance_leakage.py -v

CI: .github/workflows/ci.yml runs this on every push/PR.
"""
from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path

import pandas as pd
import pytest

ROOT    = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "hydrasense.db"

from backend.provenance import (
    ProvenanceTag,
    ALLOWED_TAGS,
    SCIENCE_ALLOWED,
    validate_tag,
    assert_no_simulated_in_features,
    is_science_allowed,
    provenance_for_source,
)


# ── 1. Enum completeness ────────────────────────────────────────────────────

class TestProvenanceEnum:
    def test_has_exactly_three_tags(self):
        assert {t.value for t in ProvenanceTag} == {
            "REAL_VALIDATED", "REAL_RECONSTRUCTED", "SIMULATED"
        }, "ProvenanceTag must have exactly the three canonical values."

    def test_allowed_tags_matches_enum(self):
        assert ALLOWED_TAGS == {t.value for t in ProvenanceTag}

    def test_science_allowed_excludes_simulated(self):
        assert ProvenanceTag.SIMULATED not in SCIENCE_ALLOWED
        assert ProvenanceTag.REAL_VALIDATED in SCIENCE_ALLOWED
        assert ProvenanceTag.REAL_RECONSTRUCTED in SCIENCE_ALLOWED

    def test_str_serialisation(self):
        """str(tag) must equal tag.value — needed for JSON/SQLite compat."""
        for tag in ProvenanceTag:
            assert str(tag) == tag.value

    def test_enum_inherits_from_str(self):
        """ProvenanceTag must be str-compatible for Pydantic / JSON serialisation."""
        assert isinstance(ProvenanceTag.REAL_VALIDATED, str)


# ── 2. validate_tag ─────────────────────────────────────────────────────────

class TestValidateTag:
    def test_accepts_all_canonical_strings(self):
        for tag in ProvenanceTag:
            assert validate_tag(tag.value) == tag

    def test_accepts_enum_instances(self):
        for tag in ProvenanceTag:
            assert validate_tag(tag) == tag

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Invalid provenance tag"):
            validate_tag("")

    def test_rejects_unknown_string(self):
        with pytest.raises(ValueError, match="Invalid provenance tag"):
            validate_tag("FAKE_TAG")

    def test_rejects_lowercase(self):
        """Tags are case-sensitive — 'simulated' != 'SIMULATED'."""
        with pytest.raises(ValueError):
            validate_tag("simulated")

    def test_rejects_none_like_string(self):
        with pytest.raises(ValueError):
            validate_tag("None")


# ── 3. assert_no_simulated_in_features ──────────────────────────────────────

class TestLeakageGuard:
    def test_passes_on_all_real_validated(self):
        df = pd.DataFrame({"provenance": ["REAL_VALIDATED", "REAL_VALIDATED"]})
        # Must not raise
        assert_no_simulated_in_features(df, source_label="test_all_real")

    def test_passes_on_all_real_reconstructed(self):
        df = pd.DataFrame({"provenance": ["REAL_RECONSTRUCTED", "REAL_RECONSTRUCTED"]})
        assert_no_simulated_in_features(df, source_label="test_all_reconstructed")

    def test_passes_on_mixed_real_tags(self):
        df = pd.DataFrame({"provenance": ["REAL_VALIDATED", "REAL_RECONSTRUCTED"]})
        assert_no_simulated_in_features(df, source_label="test_mixed_real")

    def test_raises_on_single_simulated_row(self):
        df = pd.DataFrame({"provenance": ["REAL_VALIDATED", "SIMULATED"]})
        with pytest.raises(RuntimeError, match="LEAKAGE DETECTED"):
            assert_no_simulated_in_features(df, source_label="test_one_simulated")

    def test_raises_on_all_simulated(self):
        df = pd.DataFrame({"provenance": ["SIMULATED", "SIMULATED", "SIMULATED"]})
        with pytest.raises(RuntimeError, match="LEAKAGE DETECTED"):
            assert_no_simulated_in_features(df, source_label="test_all_simulated")

    def test_raises_on_missing_provenance_column(self):
        df = pd.DataFrame({"risk_score": [0.5, 0.8], "tier": ["Yellow", "Orange"]})
        with pytest.raises(RuntimeError, match="missing a 'provenance' column"):
            assert_no_simulated_in_features(df, source_label="test_no_col")

    def test_error_message_includes_source_label(self):
        df = pd.DataFrame({"provenance": ["SIMULATED"]})
        with pytest.raises(RuntimeError, match="my_pipeline_stage"):
            assert_no_simulated_in_features(df, source_label="my_pipeline_stage")

    def test_error_message_includes_row_count(self):
        df = pd.DataFrame({"provenance": ["SIMULATED"] * 5})
        with pytest.raises(RuntimeError, match="5 SIMULATED"):
            assert_no_simulated_in_features(df, source_label="test_count")

    def test_passes_on_empty_dataframe(self):
        """An empty feature table has no SIMULATED rows — should pass."""
        df = pd.DataFrame({"provenance": pd.Series([], dtype=str)})
        assert_no_simulated_in_features(df, source_label="test_empty")


# ── 4. provenance_for_source ────────────────────────────────────────────────

class TestProvenanceForSource:
    def test_live_maps_to_real_validated(self):
        assert provenance_for_source("live") == ProvenanceTag.REAL_VALIDATED

    def test_cached_maps_to_real_validated(self):
        assert provenance_for_source("cached") == ProvenanceTag.REAL_VALIDATED

    def test_simulated_maps_to_simulated(self):
        assert provenance_for_source("simulated") == ProvenanceTag.SIMULATED

    def test_demo_maps_to_simulated(self):
        assert provenance_for_source("demo") == ProvenanceTag.SIMULATED

    def test_fallback_maps_to_simulated(self):
        assert provenance_for_source("fallback") == ProvenanceTag.SIMULATED

    def test_synthetic_maps_to_simulated(self):
        assert provenance_for_source("synthetic") == ProvenanceTag.SIMULATED

    def test_case_insensitive(self):
        assert provenance_for_source("SIMULATED") == ProvenanceTag.SIMULATED
        assert provenance_for_source("Live") == ProvenanceTag.REAL_VALIDATED


# ── 5. is_science_allowed ───────────────────────────────────────────────────

class TestIsScienceAllowed:
    def test_real_validated_allowed(self):
        assert is_science_allowed("REAL_VALIDATED") is True

    def test_real_reconstructed_allowed(self):
        assert is_science_allowed("REAL_RECONSTRUCTED") is True

    def test_simulated_not_allowed(self):
        assert is_science_allowed("SIMULATED") is False

    def test_accepts_enum_instance(self):
        assert is_science_allowed(ProvenanceTag.REAL_VALIDATED) is True
        assert is_science_allowed(ProvenanceTag.SIMULATED) is False


# ── 6. Live DB checks (skipped if DB not present) ───────────────────────────

@pytest.mark.skipif(not DB_PATH.exists(), reason="hydrasense.db not present")
class TestLiveDatabase:
    def _connect(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _has_col(self, conn, table: str, col: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == col for r in rows)

    # ── 6a. risk_scores ──────────────────────────────────────────────────

    def test_risk_scores_has_provenance_column(self):
        conn = self._connect()
        try:
            assert self._has_col(conn, "risk_scores", "provenance"), (
                "risk_scores table is missing the 'provenance' column. "
                "Run backend.database.init_db() to apply the migration."
            )
        finally:
            conn.close()

    def test_no_null_provenance_on_scored_risk_rows(self):
        """
        Any risk_scores row that has a non-NULL tier must also have a provenance.
        A NULL provenance on a scored row means we don't know if it's real or
        simulated — this is a data integrity failure.
        """
        conn = self._connect()
        try:
            if not self._has_col(conn, "risk_scores", "provenance"):
                pytest.skip("provenance column not yet added — run migration first")
            null_count = conn.execute(
                "SELECT COUNT(*) FROM risk_scores "
                "WHERE tier IS NOT NULL AND provenance IS NULL"
            ).fetchone()[0]
            assert null_count == 0, (
                f"{null_count} risk_scores row(s) have a tier but NULL provenance. "
                f"All scored rows must be tagged REAL_VALIDATED, "
                f"REAL_RECONSTRUCTED, or SIMULATED."
            )
        finally:
            conn.close()

    # ── 6b. historical_events ────────────────────────────────────────────

    def test_historical_events_has_provenance_column(self):
        conn = self._connect()
        try:
            assert self._has_col(conn, "historical_events", "provenance"), (
                "historical_events is missing the 'provenance' column. "
                "Run backend.database.init_db() to apply the migration."
            )
        finally:
            conn.close()

    def test_historical_events_all_have_provenance(self):
        """
        Phase 0 gate: every historical_events row must be tagged.
        Pre-migration rows will be NULL — this test finds and counts them
        so the team can grade and tag them during the Phase 0 data work.
        """
        conn = self._connect()
        try:
            if not self._has_col(conn, "historical_events", "provenance"):
                pytest.skip("provenance column not yet added — run migration first")
            null_count = conn.execute(
                "SELECT COUNT(*) FROM historical_events WHERE provenance IS NULL"
            ).fetchone()[0]
            assert null_count == 0, (
                f"{null_count} historical_event row(s) have NULL provenance. "
                f"Every event must be tagged REAL_VALIDATED, REAL_RECONSTRUCTED, "
                f"or SIMULATED before the Phase 0 gate passes. "
                f"Use the reconstruction protocol in Gap Analysis §0.3 and grade "
                f"each record A/B/C before tagging."
            )
        finally:
            conn.close()

    # ── 6c. observations ─────────────────────────────────────────────────

    def test_observations_has_provenance_column(self):
        conn = self._connect()
        try:
            assert self._has_col(conn, "observations", "provenance"), (
                "observations table is missing the 'provenance' column. "
                "Run backend.database.init_db() to apply the migration."
            )
        finally:
            conn.close()
