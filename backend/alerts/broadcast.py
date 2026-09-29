"""
backend/alerts/broadcast.py -- short Cell Broadcast text built from the same fields as the CAP alert
(v2 Sec. 10.5).  A CAP description does not fit a broadcast page, so each alert also carries:

    {TIER} {hazard} risk: {village}. {first action}. Confidence: {low|medium|high}. Ref {id}

Page arithmetic (3GPP TS 23.041 cell broadcast page = 82 octets of user data):
    GSM 7-bit  -> 93 characters per page  (extension-table characters count 2)
    UCS-2      -> 41 characters per page  (any non-GSM character forces UCS-2, e.g. regional scripts)
    up to 15 pages per message.
These figures come from the general 3GPP specification.  v2 says the exact limit and the language /
encoding rules must be checked against the current Indian (C-DoT / NDMA) profile before the template
is frozen -- that check has NOT been done; the constants below are marked provisional in every result.

The confidence word comes from backend.confidence.confidence_band, whose cut points are provisional
until the fitted confidence bands exist (v2 Sec. 9.2).  This is a technical-readiness artefact:
nothing here publishes anything.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.confidence import confidence_band  # noqa: E402

PAGE_CHARS_GSM7 = 93
PAGE_CHARS_UCS2 = 41
MAX_PAGES_PROTOCOL = 15
DEFAULT_MAX_PAGES = 2
PROVISIONAL = ("page_chars_gsm7", "page_chars_ucs2", "confidence_word_cut_points")

# GSM 03.38 basic character set (subset that matters here) and extension table.
_GSM7_BASIC = ("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
               "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
_GSM7_EXT = "^{}\\[~]|€"

TRIGGER_ACTIONS = {
    "CLOUDBURST_FLASH": "Leave stream banks now",
    "SATURATION_FLOOD": "Move from riverbank before peak",
    "SATURATION_LANDSLIDE": "Move away from steep slopes",
    "LANDSLIDE_DAM": "Evacuate downstream of blocked stream",
    "COMPOUND_CASCADE": "Leave slopes and low ground now",
}
DEFAULT_ACTION = "Take precautions now"
TRIGGER_HAZARD = {
    "CLOUDBURST_FLASH": "flood", "SATURATION_FLOOD": "flood", "SATURATION_LANDSLIDE": "landslide",
    "LANDSLIDE_DAM": "flood", "COMPOUND_CASCADE": "flood+landslide",
}


def gsm7_length(text: str) -> int | None:
    """Length in GSM 7-bit septets (extension chars = 2), or None if any char needs UCS-2."""
    n = 0
    for ch in text:
        if ch in _GSM7_BASIC:
            n += 1
        elif ch in _GSM7_EXT:
            n += 2
        else:
            return None
    return n


def encoding_and_length(text: str) -> tuple[str, int, int]:
    """('GSM7' | 'UCS2', length in units, page size)."""
    g = gsm7_length(text)
    if g is not None:
        return "GSM7", g, PAGE_CHARS_GSM7
    return "UCS2", len(text), PAGE_CHARS_UCS2


def paginate(text: str, page_size: int) -> list[str]:
    """Split on spaces into pages of at most `page_size` units (hard-splits an over-long word)."""
    pages, cur = [], ""
    for word in text.split(" "):
        while len(word) > page_size:
            if cur:
                pages.append(cur); cur = ""
            pages.append(word[:page_size]); word = word[page_size:]
        cand = word if not cur else cur + " " + word
        if len(cand) <= page_size:
            cur = cand
        else:
            pages.append(cur); cur = word
    if cur:
        pages.append(cur)
    return pages


def _compose(tier: str, hazard: str, village: str, action: str, confidence_word: str, alert_id: str) -> str:
    return f"{tier.upper()} {hazard} risk: {village}. {action}. Confidence: {confidence_word}. Ref {alert_id}"


def build_broadcast(
    tier: str,
    trigger_type: str | None,
    villages: Sequence[str],
    confidence_score: float,
    alert_id: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    action: str | None = None,
) -> dict:
    """
    Build the broadcast text.  If it exceeds `max_pages`, shorten in a fixed, visible order:
    (1) list fewer villages as "A (+N more)", (2) shorten the action to a generic one.  Never drops
    the tier, the hazard, the confidence word or the reference id.
    """
    max_pages = min(max_pages, MAX_PAGES_PROTOCOL)
    hazard = TRIGGER_HAZARD.get(trigger_type or "", "flood/landslide")
    word = confidence_band(confidence_score)
    act = action or TRIGGER_ACTIONS.get(trigger_type or "", DEFAULT_ACTION)
    vs = [v for v in villages if v] or ["your area"]
    notes: list[str] = []

    def label(k: int) -> str:
        return vs[0] if k >= len(vs) and len(vs) == 1 else (
            ", ".join(vs) if k >= len(vs) else f"{', '.join(vs[:k])} (+{len(vs) - k} more)")

    text = ""
    for k in range(len(vs), 0, -1):
        text = _compose(tier, hazard, label(k), act, word, alert_id)
        enc, length, page = encoding_and_length(text)
        if -(-length // page) <= max_pages:
            if k < len(vs):
                notes.append(f"villages shortened to {k} of {len(vs)}")
            break
    else:
        act = "Move to safety"
        text = _compose(tier, hazard, label(1), act, word, alert_id)
        notes.append("action shortened to a generic one")
    enc, length, page = encoding_and_length(text)
    pages = paginate(text, page)
    return dict(text=text, encoding=enc, length_units=length, page_size=page, pages=pages,
                page_count=len(pages), fits=len(pages) <= max_pages, notes=notes,
                confidence_word=word, provisional_constants=list(PROVISIONAL),
                status="Exercise draft: not published (no sponsored SACHET / Cell Broadcast access)")
