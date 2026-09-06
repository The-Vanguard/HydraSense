"""
backend/alerts/cap_generator.py — Phase 11
Generates CAP 1.2 XML per SRS.md Section 17.3.

Structure matches the frozen example exactly:
  <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
    <identifier>HYDRASENSE-WYD-YYYY-NNNNNN</identifier>
    <sender>hydrasense.sih2026@example.org</sender>
    <sent>2026-08-30T14:32:00+05:30</sent>
    <status>Actual</status>
    <msgType>Alert</msgType>
    <scope>Public</scope>
    <info>
      <category>Geo</category>
      <event>Flash Flood / Landslide Risk</event>
      <urgency>Immediate</urgency>
      <severity>Severe | Moderate</severity>
      <certainty>Likely</certainty>
      <headline>High flash-flood/landslide risk: {village}, Wayanad</headline>
      <description>...</description>
      <area>
        <areaDesc>{village} ward, Wayanad</areaDesc>
        <polygon>...H3 hex boundary...</polygon>
      </area>
    </info>
  </alert>

SRS §12 constraint: lead_time is HOUR-GRANULAR only (multiple of 60 min).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Optional

import h3

# Wayanad pilot village names — used in headline/areaDesc
_HEX_VILLAGE: dict[str, str] = {
    "8860064e61fffff": "Mundakkai",
    "8860064e63fffff": "Mundakkai",
    "8860064e65fffff": "Mundakkai",
    "8860064e67fffff": "Mundakkai",
    "8860064e69fffff": "Mundakkai",
    "8860064e29fffff": "Mundakkai",
    "8860064e2dfffff": "Mundakkai",
    "8860064e05fffff": "Mundakkai",
    "8860064e0dfffff": "Mundakkai",
    "8860064f59fffff": "Mundakkai",
    "8860064f5bfffff": "Mundakkai",
    "8860064e6bfffff": "Chooralmala",
    "8860064e41fffff": "Chooralmala",
    "8860064e43fffff": "Chooralmala",
    "8860064e45fffff": "Chooralmala",
    "8860064e4dfffff": "Chooralmala",
    "8860064e01fffff": "Chooralmala",
    "8860064e09fffff": "Chooralmala",
    "8860064e47fffff": "Attamala",
    "8860064e49fffff": "Attamala",
    "8860064e4bfffff": "Attamala",
    "8860064e55fffff": "Attamala",
    "8860064e5dfffff": "Attamala",
    "8860064e0bfffff": "Attamala",
    "8860064e6dfffff": "Punjirimattom",
    "8860064191fffff": "Punjirimattom",
    "8860064195fffff": "Punjirimattom",
    "88600641b1fffff": "Punjirimattom",
    "88600641b7fffff": "Punjirimattom",
}

CAP_NS  = "urn:oasis:names:tc:emergency:cap:1.2"
SENDER  = "hydrasense.sih2026@example.org"
IST_OFFSET = timedelta(hours=5, minutes=30)


def _ist_now() -> str:
    """Current time in IST, formatted as ISO 8601 with +05:30 offset (per SRS §17.3 example)."""
    now_utc = datetime.now(timezone.utc)
    ist = now_utc + IST_OFFSET
    return ist.strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _hex_polygon(hex_id: str) -> str:
    """
    Convert H3 hex to CAP polygon string: space-separated 'lat,lon' pairs, closed ring.
    h3.cell_to_boundary() returns list of (lat, lng) tuples.
    """
    try:
        boundary = h3.cell_to_boundary(hex_id)  # [(lat, lng), ...]
        # CAP polygon: space-separated lat,lon pairs, ring closed by repeating first vertex
        coords = " ".join(f"{lat},{lng}" for lat, lng in boundary)
        first = f"{boundary[0][0]},{boundary[0][1]}"
        return f"{coords} {first}"
    except Exception:
        return ""


def _lead_time_text(lead_time_min: Optional[int], lead_time_basis: str) -> str:
    """
    SRS §12: lead_time_min is hour-granular (multiple of 60) or None.
    Never fabricate a sub-hour number.
    """
    if lead_time_min is None or lead_time_basis == "no_red_crossing_in_forecast_window":
        return "No Red-tier crossing detected in forecast window."
    hours = lead_time_min // 60
    horizon = lead_time_basis  # e.g. "forecast_crossing_t+2h"
    return f"Estimated lead time: {lead_time_min} minutes ({hours}h, {horizon}, Open-Meteo)."


def _shelter_text(nearest_shelter: Optional[dict]) -> str:
    if not nearest_shelter:
        return "Nearest shelter: see district emergency management."
    name = nearest_shelter.get("name", "unknown")
    dist = nearest_shelter.get("distance_m")
    if dist is not None:
        dist_km = round(dist / 1000, 1)
        return f"Nearest known shelter: {name} ({dist_km} km, static lookup)."
    return f"Nearest known shelter: {name} (static lookup)."


def generate_cap_xml(
    alert_id: str,
    hex_id: str,
    tier: str,
    risk_score: float,
    confidence_score: float,
    lead_time_min: Optional[int],
    lead_time_basis: str,
    nearest_shelter: Optional[dict] = None,
    sent_ist: Optional[str] = None,
) -> tuple[str, dict]:
    """
    Returns (cap_xml_string, cap_payload_dict).
    cap_payload_dict is the structured version for JSONB storage.

    SRS §17.3: severity = Severe (Red) | Moderate (Orange).
    """
    village   = _HEX_VILLAGE.get(hex_id, "Wayanad pilot area")
    sent      = sent_ist or _ist_now()
    severity  = "Severe" if tier == "Red" else "Moderate"
    polygon   = _hex_polygon(hex_id)

    headline    = f"High flash-flood/landslide risk: {village}, Wayanad"
    lead_text   = _lead_time_text(lead_time_min, lead_time_basis)
    shelter_txt = _shelter_text(nearest_shelter)
    description = (
        f"Risk score {int(risk_score)}/100 ({tier.upper()}), "
        f"confidence {int(confidence_score)}/100. "
        f"{lead_text} "
        f"{shelter_txt}"
    )

    # Build XML tree
    root = ET.Element("alert", xmlns=CAP_NS)
    ET.SubElement(root, "identifier").text = alert_id
    ET.SubElement(root, "sender").text     = SENDER
    ET.SubElement(root, "sent").text       = sent
    ET.SubElement(root, "status").text     = "Actual"
    ET.SubElement(root, "msgType").text    = "Alert"
    ET.SubElement(root, "scope").text      = "Public"

    info = ET.SubElement(root, "info")
    ET.SubElement(info, "category").text   = "Geo"
    ET.SubElement(info, "event").text      = "Flash Flood / Landslide Risk"
    ET.SubElement(info, "urgency").text    = "Immediate"
    ET.SubElement(info, "severity").text   = severity
    ET.SubElement(info, "certainty").text  = "Likely"
    ET.SubElement(info, "headline").text   = headline
    ET.SubElement(info, "description").text = description

    area = ET.SubElement(info, "area")
    ET.SubElement(area, "areaDesc").text = f"{village} ward, Wayanad"
    if polygon:
        ET.SubElement(area, "polygon").text = polygon

    ET.register_namespace("", CAP_NS)
    xml_str = ET.tostring(root, encoding="unicode", xml_declaration=False)
    # Wrap with declaration + namespace
    cap_xml = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'

    cap_payload = {
        "identifier":        alert_id,
        "sender":            SENDER,
        "sent":              sent,
        "status":            "Actual",
        "msgType":           "Alert",
        "scope":             "Public",
        "tier":              tier,
        "severity":          severity,
        "risk_score":        risk_score,
        "confidence_score":  confidence_score,
        "lead_time_min":     lead_time_min,
        "lead_time_basis":   lead_time_basis,
        "headline":          headline,
        "description":       description,
        "village":           village,
        "hex_id":            hex_id,
        "polygon":           polygon,
        "nearest_shelter":   nearest_shelter,
    }

    return cap_xml, cap_payload
