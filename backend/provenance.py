"""
backend/provenance.py
Provenance policy for HydraSense v2 (Gap Analysis §0.2 / §0.3).

Three allowed tags:
  REAL_VALIDATED      — taken directly from an agency or peer-reviewed
                        inventory and used as published.
  REAL_RECONSTRUCTED  — a real event whose missing fields (time, coordinates,
                        rainfall) were filled in from public sources using the
                        reconstruction protocol in §0.3.
  SIMULATED           — invented for demos and pipeline tests only.

Rules (locked, Gap Analysis §0.2):
  1. Every data row must carry one of these three values in its `provenance`
     column.  A NULL provenance is treated as an error.
  2. SIMULATED rows may exist in the database for IoT replay and demo purposes,
     but they are NEVER allowed to enter training features, validation splits,
     calibration runs, or any reported metric.
  3. The CI leakage test (tests/test_provenance_leakage.py) enforces rule 2
     automatically and fails the build if the rule is broken.
  4. assert_no_simulated_in_features() is called at feature-table write time
     as a second-line defence inside the ML pipeline.

Design system rule (Gap Analysis Decision 5): this module is UI-agnostic.
Map/UI provenance badge rendering is handled by hydrasense-theme.css and the
deck.gl layer config (hydrasense-map-theme.js).  See also:
  - UI badge classes: .badge-provenance-live, .badge-provenance-cached,
                      .badge-provenance-simulated  (hydrasense-theme.css)
  - API payload field: `provenance` in RiskMapEntry, EventMapEntry (models.py)
"""
from __future__ import annotations

from enum import Enum
from typing import Union


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class ProvenanceTag(str, Enum):
    """
    Canonical provenance tags.  Inherits from str so instances serialise to
    their string value directly (compatible with JSON, SQLite TEXT, Pydantic).
    """
    REAL_VALIDATED     = "REAL_VALIDATED"
    REAL_RECONSTRUCTED = "REAL_RECONSTRUCTED"
    SIMULATED          = "SIMULATED"

    def __str__(self) -> str:          # ensure str(tag) == tag.value
        return self.value

    def __repr__(self) -> str:
        return f"ProvenanceTag.{self.name}"


# Convenience sets
ALLOWED_TAGS: frozenset[str] = frozenset(t.value for t in ProvenanceTag)

# Tags that may enter training features and validation splits (§0.3 table)
SCIENCE_ALLOWED: frozenset[ProvenanceTag] = frozenset({
    ProvenanceTag.REAL_VALIDATED,
    ProvenanceTag.REAL_RECONSTRUCTED,
})


# ---------------------------------------------------------------------------
# Parser / validator
# ---------------------------------------------------------------------------

def validate_tag(value: Union[str, ProvenanceTag]) -> ProvenanceTag:
    """
    Parse and validate a provenance string or enum value.

    Args:
        value: a string or ProvenanceTag to validate.

    Returns:
        The corresponding ProvenanceTag member.

    Raises:
        ValueError: if the value is not one of the three canonical tags.

    Examples:
        >>> validate_tag("REAL_VALIDATED")
        ProvenanceTag.REAL_VALIDATED
        >>> validate_tag(ProvenanceTag.SIMULATED)
        ProvenanceTag.SIMULATED
        >>> validate_tag("FAKE")
        ValueError: Invalid provenance tag 'FAKE'. Must be one of: ...
    """
    if isinstance(value, ProvenanceTag):
        return value
    try:
        return ProvenanceTag(value)
    except ValueError:
        raise ValueError(
            f"Invalid provenance tag '{value}'. "
            f"Must be one of: {sorted(ALLOWED_TAGS)}"
        )


# ---------------------------------------------------------------------------
# Runtime leakage guard
# ---------------------------------------------------------------------------

def assert_no_simulated_in_features(df, source_label: str = "unknown") -> None:
    """
    Runtime guard: call before any feature table write, train/val split,
    or validation run.

    Raises RuntimeError if:
      - the DataFrame is missing a 'provenance' column entirely, OR
      - any row has provenance == 'SIMULATED'.

    This is the second line of defence after the CI leakage test; both must
    be satisfied (CI catches the static state, this catches dynamic runtime
    generation paths that CI cannot see).

    Args:
        df:           a pandas DataFrame that MUST have a 'provenance' column.
        source_label: human-readable name shown in the error message (e.g. the
                      file path or pipeline stage name).

    Raises:
        RuntimeError: on missing column or SIMULATED rows found.

    Example:
        feature_df = build_feature_table(region_code)
        assert_no_simulated_in_features(feature_df, source_label="build_feature_table(wayanad-kl)")
        model.fit(feature_df)
    """
    if "provenance" not in df.columns:
        raise RuntimeError(
            f"[provenance] DataFrame from '{source_label}' is missing a "
            f"'provenance' column. Every feature row must carry a provenance "
            f"tag (REAL_VALIDATED or REAL_RECONSTRUCTED for science use; "
            f"SIMULATED for demos only). Add the column at the point where the "
            f"row is created."
        )

    simulated_mask = df["provenance"] == ProvenanceTag.SIMULATED.value
    bad = df[simulated_mask]
    if not bad.empty:
        sample_ids = (
            bad["event_id"].tolist()[:5]
            if "event_id" in bad.columns
            else bad.index[:5].tolist()
        )
        raise RuntimeError(
            f"[provenance] LEAKAGE DETECTED in '{source_label}': "
            f"{len(bad)} SIMULATED row(s) found in feature table. "
            f"First offenders (id/index): {sample_ids}. "
            f"SIMULATED data must never enter training features, validation "
            f"splits, calibration, or any reported metric (Gap Analysis §0.2 "
            f"rule 3). Filter SIMULATED rows before calling this function, "
            f"or fix the data source to label real data correctly."
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def is_science_allowed(tag: Union[str, ProvenanceTag]) -> bool:
    """Return True if this provenance tag is permitted in train/val splits."""
    return validate_tag(tag) in SCIENCE_ALLOWED


def provenance_for_source(source: str) -> ProvenanceTag:
    """
    Infer a provenance tag from a data-source descriptor string.

    Used by the onboarding pipeline to stamp hex features when the source
    comes from a live data fetch vs a fallback/simulated path.

    source strings recognised:
      "live"      → REAL_VALIDATED   (fetched from a real external source)
      "cached"    → REAL_VALIDATED   (previously fetched real data on disk)
      "simulated" → SIMULATED
      "demo"      → SIMULATED
      "fallback"  → SIMULATED        (synthetic fallback, must be labeled)
      anything else → REAL_VALIDATED (conservative default; caller should audit)
    """
    s = source.lower().strip()
    if s in ("simulated", "demo", "fallback", "synthetic"):
        return ProvenanceTag.SIMULATED
    return ProvenanceTag.REAL_VALIDATED
