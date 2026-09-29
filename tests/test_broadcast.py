"""tests/test_broadcast.py -- Cell Broadcast short text (v2 Sec. 10.5)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.alerts import broadcast as bc  # noqa: E402


def test_template_matches_v2_and_keeps_required_fields():
    out = bc.build_broadcast("Red", "SATURATION_LANDSLIDE", ["Mundakkai"], 80, "HS-WYD-000123")
    assert out["text"] == ("RED landslide risk: Mundakkai. Move away from steep slopes. "
                           "Confidence: high. Ref HS-WYD-000123")
    # 95 septets: the v2 template with a realistic reference id needs 2 pages, not 1
    assert out["encoding"] == "GSM7" and out["fits"] and out["length_units"] == 95 and out["page_count"] == 2
    assert "Exercise draft" in out["status"] and "page_chars_gsm7" in out["provisional_constants"]


def test_hazard_and_action_follow_trigger_type():
    assert "flood risk" in bc.build_broadcast("Orange", "CLOUDBURST_FLASH", ["A"], 50, "1")["text"]
    assert "flood+landslide" in bc.build_broadcast("Red", "COMPOUND_CASCADE", ["A"], 50, "1")["text"]
    assert "blocked stream" in bc.build_broadcast("Red", "LANDSLIDE_DAM", ["A"], 50, "1")["text"]
    unknown = bc.build_broadcast("Orange", None, ["A"], 50, "1")
    assert "flood/landslide risk" in unknown["text"] and bc.DEFAULT_ACTION in unknown["text"]


def test_confidence_word_comes_from_bands():
    for score, word in ((85, "high"), (50, "medium"), (10, "low")):
        assert f"Confidence: {word}" in bc.build_broadcast("Red", None, ["A"], score, "1")["text"]


def test_gsm7_extension_characters_count_double():
    assert bc.gsm7_length("abc") == 3
    assert bc.gsm7_length("a[b]") == 6                       # '[' and ']' are 2 each
    assert bc.gsm7_length("नमस्ते") is None                    # needs UCS-2


def test_regional_script_forces_ucs2_and_smaller_pages():
    out = bc.build_broadcast("Red", "SATURATION_LANDSLIDE", ["मुंडक्काई"], 60, "1", max_pages=4)
    assert out["encoding"] == "UCS2" and out["page_size"] == bc.PAGE_CHARS_UCS2
    assert all(len(p) <= 41 for p in out["pages"])


def test_many_villages_are_compacted_visibly_within_max_pages():
    villages = [f"Village-number-{i}" for i in range(20)]
    out = bc.build_broadcast("Red", "SATURATION_LANDSLIDE", villages, 60, "REF-1", max_pages=2)
    assert out["fits"] and out["page_count"] <= 2
    assert "more)" in out["text"] and any("villages shortened" in n for n in out["notes"])
    assert out["text"].startswith("RED landslide risk") and out["text"].endswith("Ref REF-1")


def test_extremely_long_village_falls_back_to_generic_action_and_still_keeps_ref():
    out = bc.build_broadcast("Red", "LANDSLIDE_DAM", ["X" * 120], 60, "REF-9", max_pages=1)
    assert any("generic" in n for n in out["notes"]) and out["text"].endswith("Ref REF-9")


def test_reports_when_it_cannot_fit_instead_of_hiding_it():
    out = bc.build_broadcast("Red", "SATURATION_LANDSLIDE", ["Village-number-0"], 60, "HS-WYD-000123-EXTRA", max_pages=1)
    assert out["fits"] is False and out["page_count"] == 2 and out["text"].endswith("Ref HS-WYD-000123-EXTRA")


def test_paginate_never_exceeds_page_size():
    text = "word " * 80 + "supercalifragilistic" * 10
    pages = bc.paginate(text.strip(), 93)
    assert all(len(p) <= 93 for p in pages) and " ".join(pages).replace("  ", " ")


def test_protocol_page_cap_and_no_villages():
    assert bc.build_broadcast("Red", None, ["A"], 60, "1", max_pages=99)["page_count"] <= bc.MAX_PAGES_PROTOCOL
    assert "your area" in bc.build_broadcast("Red", None, [], 60, "1")["text"]
