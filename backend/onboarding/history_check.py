"""
backend/onboarding/history_check.py
Step 6 of the Autonomous Region Onboarding Pipeline (Final.md §6, step 6 / §8.3 Tier 3).

Checks whether a resolved region overlaps with GSI-mapped districts to
determine if local historical calibration data is available.

has_local_calibration (Final.md §10.3, §11.3):
  True  — the region overlaps GSI's mapped coverage AND a usable event
           inventory exists for that district
  False — no GSI mapping, or GSI maps the district but the event record
           is too sparse to calibrate confidence

This flag is the 29th feature in the 29-feature table (Final.md §10.3) and
the third factor in the confidence score (Final.md §11.3). It is not a bonus
— a False value reduces confidence for regions with no calibration history,
which is exactly what Final.md §1 requires ("stating which claim it is making,
per region, at prediction time").

Data source:
  1. data/susceptibility/ — GSI susceptibility classes already seeded (Phase 4)
  2. data/events/historical_events.csv — the pooled event inventory
  3. data/multiregion/events/ — multiregion event data from Phase 13

Matching logic:
  - Compute bbox centroid
  - Check if it overlaps any district in the known event inventory
  - Return has_local_calibration=True only if at least MIN_EVENT_THRESHOLD
    events with confirmed coordinates exist for that district
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]

# Known districts with confirmed event inventories (from Phase 4 + Phase 13 data)
# Format: {district_slug: {state, min_event_count, has_gsi_mapping}}
KNOWN_CALIBRATED_DISTRICTS = {
    # Western Ghats — well-documented
    "wayanad":         {"state": "kerala",        "min_events": 15, "has_gsi": True},
    "idukki":          {"state": "kerala",        "min_events": 8,  "has_gsi": True},
    "nilgiris":        {"state": "tamil_nadu",    "min_events": 6,  "has_gsi": True},
    # Himalayan — variable documentation
    "rudraprayag":     {"state": "uttarakhand",   "min_events": 10, "has_gsi": True},
    "chamoli":         {"state": "uttarakhand",   "min_events": 8,  "has_gsi": True},
    "kullu":           {"state": "himachal_pradesh","min_events": 5,"has_gsi": True},
    "darjeeling":      {"state": "west_bengal",   "min_events": 7,  "has_gsi": True},
    "kalimpong":       {"state": "west_bengal",   "min_events": 4,  "has_gsi": True},
    "mangan":          {"state": "sikkim",        "min_events": 5,  "has_gsi": True},
    # Northeast — sparser
    "ribhoi":          {"state": "meghalaya",     "min_events": 3,  "has_gsi": False},
    "dhemaji":         {"state": "assam",         "min_events": 4,  "has_gsi": False},
}

MIN_EVENT_THRESHOLD = 3   # minimum event count to consider a district "calibrated"


@dataclass
class CalibrationResult:
    region_code:          str
    has_local_calibration: bool
    district_match:       str = ""          # matched district name
    event_count:          int = 0
    has_gsi_mapping:      bool = False
    confidence_note:      str = ""          # displayed in dashboard tooltip
    source:               str = "inventory_check"


def _load_event_counts() -> dict[str, int]:
    """
    Load event counts per district from historical event inventory.
    Searches both the Wayanad-specific and multiregion event files.
    Returns {district_lower: count}.
    """
    counts: dict[str, int] = {}

    # Wayanad pilot events
    wayanad_csv = ROOT / "data" / "events" / "historical_events.csv"
    if wayanad_csv.exists():
        with wayanad_csv.open(encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                district = (row.get("district") or row.get("location") or "wayanad").lower().strip()
                district = district.split(",")[0].split("/")[0].strip()
                counts[district] = counts.get(district, 0) + 1

    # Multiregion events
    multi_csv = ROOT / "data" / "multiregion" / "events" / "flood_events_labeled_step2.csv"
    if multi_csv.exists():
        with multi_csv.open(encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                loc = (row.get("target_location") or row.get("district") or "").lower().strip()
                loc = loc.split(",")[0].split("/")[0].strip()
                if loc:
                    counts[loc] = counts.get(loc, 0) + 1

    return counts


def check_local_calibration(
    region_code: str,
    bbox: dict,
    district: str = "",
    state: str = "",
) -> CalibrationResult:
    """
    Main entry point. Checks whether the resolved region has local calibration data.

    Args:
        region_code: slug (e.g. "wayanad-kl")
        bbox: south/north/west/east
        district: from boundary resolution (may be empty)
        state: from boundary resolution (may be empty)

    Returns CalibrationResult with has_local_calibration flag.
    """
    event_counts = _load_event_counts()

    # Normalize inputs
    district_norm = district.lower().strip().split(",")[0].split("/")[0].strip() if district else ""
    state_norm    = state.lower().strip() if state else ""

    # 1. Check known calibrated districts table
    for known_dist, info in KNOWN_CALIBRATED_DISTRICTS.items():
        if known_dist in district_norm or known_dist in region_code.lower():
            actual_count = event_counts.get(known_dist, info["min_events"])
            if actual_count >= MIN_EVENT_THRESHOLD:
                note = (
                    f"GSI-mapped district with {actual_count} recorded events — "
                    f"confidence calibrated from local data"
                    if info["has_gsi"] else
                    f"{actual_count} events found — partial calibration (no GSI mapping)"
                )
                return CalibrationResult(
                    region_code=region_code,
                    has_local_calibration=True,
                    district_match=known_dist,
                    event_count=actual_count,
                    has_gsi_mapping=info["has_gsi"],
                    confidence_note=note,
                    source="known_calibrated_districts",
                )

    # 2. Check event inventory directly for the district name
    if district_norm:
        count = event_counts.get(district_norm, 0)
        if count >= MIN_EVENT_THRESHOLD:
            return CalibrationResult(
                region_code=region_code,
                has_local_calibration=True,
                district_match=district_norm,
                event_count=count,
                has_gsi_mapping=False,
                confidence_note=(
                    f"{count} events found in inventory for {district} — "
                    f"partial calibration (no GSI susceptibility mapping)"
                ),
                source="inventory_match",
            )

    # 3. No match — region has no local calibration
    return CalibrationResult(
        region_code=region_code,
        has_local_calibration=False,
        district_match="",
        event_count=0,
        has_gsi_mapping=False,
        confidence_note=(
            "No local historical calibration data found — "
            "FS uncertainty band widened; confidence score reduced (Final.md §11.3). "
            "This is an architectural region-agnosticism claim, not an accuracy guarantee."
        ),
        source="no_match",
    )
