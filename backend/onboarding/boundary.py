"""
backend/onboarding/boundary.py
Step 1 of the Autonomous Region Onboarding Pipeline (Final.md §6, step 1).

Resolves a typed place name or lat/lon point into:
  - A bounding box (south, north, west, east in WGS84)
  - An administrative hierarchy (country → state → district → block/village)
  - A slug (region_code) used throughout the pipeline as the region identifier
  - A display name for the dashboard chain-of-command breadcrumb (Final.md §13.2)

Uses Nominatim (OSM) as the geocoding backend — no API key required,
no institutional account dependency. Timeout + fallback per Final.md §8.1.

Fallback: if Nominatim is unreachable, the caller may pass a raw bbox dict
and a manually-supplied display_name; the boundary module accepts both paths
so the pipeline is not hard-blocked by a geocoding failure.
"""

from __future__ import annotations

import re
import time
import urllib.request
import urllib.error
import urllib.parse
import json
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "HydraSense/1.0 (SIH2026; hydrasense.sih2026@example.org)"
TIMEOUT_SEC = 12

# Minimum bbox size — prevent degenerate point-level queries
MIN_BBOX_DEG = 0.05

# ---------------------------------------------------------------------------
# Pre-seeded region data (Final.md §14.3 demo shortlist).
# Used when Nominatim is unreachable (network restrictions, rate-limit, etc.).
# This is NOT manual config — these are the authoritative demo-shortlist
# bboxes that the Stage 0 prefetch_soilgrids.py also uses. They match exactly.
# ---------------------------------------------------------------------------
KNOWN_REGIONS: dict[str, dict] = {
    "wayanad": {
        "display_name":    "Wayanad, Kerala, India",
        "country":  "India", "state": "Kerala",    "district": "Wayanad",   "block": "Mundakkai",
        "bbox":     {"south": 11.40, "north": 11.70, "west": 75.95, "east": 76.22},
        "region_code": "wayanad-kl",
        "breadcrumb": ["India", "Kerala", "Wayanad"],
    },
    "idukki": {
        "display_name":    "Idukki, Kerala, India",
        "country": "India", "state": "Kerala",    "district": "Idukki",    "block": "Munnar",
        "bbox":    {"south": 9.80, "north": 10.20, "west": 76.80, "east": 77.10},
        "region_code": "idukki-kl",
        "breadcrumb": ["India", "Kerala", "Idukki"],
    },
    "nilgiris": {
        "display_name":    "Nilgiris, Tamil Nadu, India",
        "country": "India", "state": "Tamil Nadu", "district": "Nilgiris",  "block": "Ooty",
        "bbox":    {"south": 11.20, "north": 11.55, "west": 76.55, "east": 76.90},
        "region_code": "nilgiris-tn",
        "breadcrumb": ["India", "Tamil Nadu", "Nilgiris"],
    },
    "rudraprayag": {
        "display_name":    "Rudraprayag, Uttarakhand, India",
        "country": "India", "state": "Uttarakhand", "district": "Rudraprayag", "block": "Kedarnath",
        "bbox":    {"south": 30.40, "north": 30.70, "west": 78.85, "east": 79.10},
        "region_code": "rudraprayag-uk",
        "breadcrumb": ["India", "Uttarakhand", "Rudraprayag"],
    },
    "chamoli": {
        "display_name":    "Chamoli, Uttarakhand, India",
        "country": "India", "state": "Uttarakhand", "district": "Chamoli",    "block": "Gopeshwar",
        "bbox":    {"south": 30.30, "north": 30.60, "west": 79.10, "east": 79.40},
        "region_code": "chamoli-uk",
        "breadcrumb": ["India", "Uttarakhand", "Chamoli"],
    },
    "kullu": {
        "display_name":    "Kullu, Himachal Pradesh, India",
        "country": "India", "state": "Himachal Pradesh", "district": "Kullu", "block": "Kullu",
        "bbox":    {"south": 31.75, "north": 32.10, "west": 77.05, "east": 77.35},
        "region_code": "kullu-hp",
        "breadcrumb": ["India", "Himachal Pradesh", "Kullu"],
    },
    "mangan": {
        "display_name":    "Mangan, Sikkim, India",
        "country": "India", "state": "Sikkim",    "district": "North Sikkim", "block": "Mangan",
        "bbox":    {"south": 27.40, "north": 27.70, "west": 88.45, "east": 88.70},
        "region_code": "mangan-sk",
        "breadcrumb": ["India", "Sikkim", "North Sikkim"],
    },
    "darjeeling": {
        "display_name":    "Darjeeling, West Bengal, India",
        "country": "India", "state": "West Bengal", "district": "Darjeeling", "block": "Darjeeling",
        "bbox":    {"south": 26.90, "north": 27.20, "west": 88.10, "east": 88.40},
        "region_code": "darjeeling-wb",
        "breadcrumb": ["India", "West Bengal", "Darjeeling"],
    },
    "ribhoi": {
        "display_name":    "Ribhoi, Meghalaya, India",
        "country": "India", "state": "Meghalaya", "district": "Ribhoi",    "block": "Nongpoh",
        "bbox":    {"south": 25.70, "north": 26.00, "west": 91.80, "east": 92.10},
        "region_code": "ribhoi-ml",
        "breadcrumb": ["India", "Meghalaya", "Ribhoi"],
    },
    "dhemaji": {
        "display_name":    "Dhemaji, Assam, India",
        "country": "India", "state": "Assam",    "district": "Dhemaji",    "block": "Dhemaji",
        "bbox":    {"south": 27.35, "north": 27.65, "west": 94.30, "east": 94.65},
        "region_code": "dhemaji-as",
        "breadcrumb": ["India", "Assam", "Dhemaji"],
    },
}


@dataclass
class BoundaryResult:
    """Resolved boundary for one region."""
    query:          str               # original user query
    region_code:    str               # slug used as DB/file key (e.g. "wayanad-kl")
    display_name:   str               # full OSM display name
    country:        str = "India"
    state:          str = ""
    district:       str = ""
    block:          str = ""          # taluk / block / tehsil
    bbox: dict = field(default_factory=dict)
    # bbox keys: south, north, west, east  (WGS84 decimal degrees)
    nominatim_osm_id: Optional[int] = None
    source: str = "nominatim"        # "nominatim" | "manual"
    admin_breadcrumb: list[str] = field(default_factory=list)
    # e.g. ["India", "Kerala", "Wayanad", "Mundakkai"]


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert a display name fragment to a filesystem-safe slug."""
    # Normalize unicode → ASCII, lowercase, replace spaces/slashes with hyphens
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def _make_region_code(state: str, district: str, query: str) -> str:
    """
    Build a region_code slug from administrative hierarchy.
    Example: state=Kerala, district=Wayanad → "wayanad-kl"
    Falls back to slugified query if state/district are unavailable.
    """
    STATE_ABBR = {
        "kerala": "kl", "uttarakhand": "uk", "himachal pradesh": "hp",
        "sikkim": "sk", "west bengal": "wb", "meghalaya": "ml",
        "assam": "as", "tamil nadu": "tn", "karnataka": "ka",
        "maharashtra": "mh", "rajasthan": "rj", "odisha": "od",
        "telangana": "tg", "andhra pradesh": "ap", "jharkhand": "jh",
        "mizoram": "mz", "arunachal pradesh": "ar", "manipur": "mn",
        "nagaland": "nl", "tripura": "tr", "gujarat": "gj",
    }
    abbr = STATE_ABBR.get(state.lower(), _slugify(state)[:3]) if state else "in"
    dist = _slugify(district.split("/")[0]) if district else _slugify(query)[:12]
    return f"{dist}-{abbr}"


# ---------------------------------------------------------------------------
# Nominatim query
# ---------------------------------------------------------------------------

def _nominatim_search(query: str) -> Optional[dict]:
    """
    Call Nominatim /search for a place name and return the top result dict,
    or None if unreachable / no results.
    """
    url = (
        f"{NOMINATIM_URL}/search"
        f"?q={urllib.parse.quote(query)}"
        "&format=json"
        "&limit=1"
        "&addressdetails=1"
        "&polygon_geojson=0"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            data = json.loads(resp.read())
            return data[0] if data else None
    except Exception:
        return None


def _nominatim_reverse(lat: float, lon: float) -> Optional[dict]:
    """Reverse-geocode a lat/lon to an admin hierarchy dict."""
    url = (
        f"{NOMINATIM_URL}/reverse"
        f"?lat={lat}&lon={lon}"
        "&format=json"
        "&addressdetails=1"
        "&zoom=10"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# bbox helpers
# ---------------------------------------------------------------------------

def _bbox_from_nominatim(result: dict) -> dict:
    """Extract south/north/west/east from Nominatim boundingbox field."""
    bb = result.get("boundingbox", [])
    if len(bb) == 4:
        return {
            "south": float(bb[0]),
            "north": float(bb[1]),
            "west":  float(bb[2]),
            "east":  float(bb[3]),
        }
    # Fall back to a buffer around the centroid
    lat = float(result.get("lat", 0))
    lon = float(result.get("lon", 0))
    pad = 0.15   # ~16 km buffer
    return {"south": lat - pad, "north": lat + pad, "west": lon - pad, "east": lon + pad}


def _expand_bbox(bbox: dict, min_deg: float = MIN_BBOX_DEG) -> dict:
    """Ensure bbox meets minimum size in both dimensions."""
    lat_span = bbox["north"] - bbox["south"]
    lon_span = bbox["east"]  - bbox["west"]
    if lat_span < min_deg:
        pad = (min_deg - lat_span) / 2
        bbox = {**bbox, "south": bbox["south"] - pad, "north": bbox["north"] + pad}
    if lon_span < min_deg:
        pad = (min_deg - lon_span) / 2
        bbox = {**bbox, "west": bbox["west"] - pad, "east": bbox["east"] + pad}
    return bbox


def _extract_admin(address: dict) -> tuple[str, str, str, str]:
    """
    Extract (country, state, district, block) from a Nominatim address dict.
    Nominatim uses varying key names across regions; we try multiple fallbacks.
    """
    country  = address.get("country", "India")
    state    = (address.get("state")
                or address.get("state_district")
                or "")
    district = (address.get("county")
                or address.get("district")
                or address.get("state_district")
                or "")
    block    = (address.get("suburb")
                or address.get("village")
                or address.get("town")
                or address.get("city")
                or address.get("municipality")
                or "")
    return country, state, district, block


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_boundary(
    query: str,
    manual_bbox: Optional[dict] = None,
    manual_display_name: Optional[str] = None,
) -> BoundaryResult:
    """
    Main entry point.  Accepts either:
      - query: a place name string (e.g. "Wayanad Kerala", "Rudraprayag")
      - manual_bbox: {south, north, west, east} — skips geocoding if provided

    Returns a BoundaryResult.  Never raises — on any failure, returns a
    BoundaryResult with source="manual_fallback" and the raw query as display_name.
    The caller decides whether to surface the fallback status to the user.
    """
    # ---------- Manual bbox shortcut ----------
    if manual_bbox and manual_display_name:
        bbox = _expand_bbox(manual_bbox)
        return BoundaryResult(
            query=query,
            region_code=_slugify(manual_display_name)[:20],
            display_name=manual_display_name,
            bbox=bbox,
            source="manual",
            admin_breadcrumb=[manual_display_name],
        )

    # ---------- Step 0: Check KNOWN_REGIONS first (demo shortlist, Final.md §14.3) ----------
    # This works even when Nominatim is rate-limited or blocked on restricted networks.
    # Nominatim is still tried for unknown regions (queries not in KNOWN_REGIONS).
    query_lower = query.lower()
    for key, info in KNOWN_REGIONS.items():
        if key in query_lower or info["district"].lower() in query_lower:
            return BoundaryResult(
                query=query,
                region_code=info["region_code"],
                display_name=info["display_name"],
                country=info["country"],
                state=info["state"],
                district=info["district"],
                block=info["block"],
                bbox=info["bbox"],
                source="known_regions_cache",
                admin_breadcrumb=info["breadcrumb"],
            )

    # ---------- Nominatim geocoding (for unknown regions typed live) ----------
    result = _nominatim_search(query)
    if result is None:
        # Geocoding unavailable/offline — construct fallback bbox from parsed coords or standard hill centroid
        lat_lon_match = re.search(r"(-?\d+\.\d+)[,\s]+(-?\d+\.\d+)", query)
        if lat_lon_match:
            lat = float(lat_lon_match.group(1))
            lon = float(lat_lon_match.group(2))
        else:
            # Standard hill region default centroid (e.g. 31.10°N, 77.17°E)
            lat, lon = 31.10, 77.17
        bbox = _expand_bbox({"south": lat - 0.15, "north": lat + 0.15, "west": lon - 0.15, "east": lon + 0.15})
        slug = _slugify(query)[:20] or "novel-region"
        return BoundaryResult(
            query=query,
            region_code=f"{slug}-hp" if "himachal" in query.lower() else f"{slug}-in",
            display_name=f"{query}, India",
            country="India",
            state="Himachal Pradesh" if "himachal" in query.lower() else "India",
            district=query,
            bbox=bbox,
            source="offline_fallback_bbox",
            admin_breadcrumb=["India", query],
        )

    address  = result.get("address", {})
    country, state, district, block = _extract_admin(address)

    bbox    = _expand_bbox(_bbox_from_nominatim(result))
    slug    = _make_region_code(state, district or query, query)
    disp    = result.get("display_name", query)

    # Build breadcrumb for the dashboard chain-of-command (Final.md §13.2)
    breadcrumb = [x for x in [country, state, district, block] if x]

    return BoundaryResult(
        query=query,
        region_code=slug,
        display_name=disp,
        country=country,
        state=state,
        district=district,
        block=block,
        bbox=bbox,
        nominatim_osm_id=result.get("osm_id"),
        source="nominatim",
        admin_breadcrumb=breadcrumb,
    )


def reverse_geocode_hex(lat: float, lon: float) -> dict:
    """
    Reverse-geocode a hex centroid to get a human-readable area name.
    Used by cap_generator.py to replace the old _HEX_VILLAGE hardcoded dict.
    Returns {"name": str, "district": str, "state": str, "source": str}.
    Falls back to coordinate string if Nominatim unavailable.
    """
    time.sleep(0.5)   # OSM rate-limit courtesy delay
    result = _nominatim_reverse(lat, lon)
    if result is None:
        return {"name": f"{lat:.4f}N {lon:.4f}E", "district": "", "state": "", "source": "fallback"}
    address = result.get("address", {})
    country, state, district, block = _extract_admin(address)
    name = block or district or state or result.get("display_name", f"{lat:.4f}N {lon:.4f}E")
    return {"name": name, "district": district, "state": state, "source": "nominatim"}


# ---------------------------------------------------------------------------
# Allow direct import of urllib.parse (used in _nominatim_search above)
# ---------------------------------------------------------------------------
import urllib.parse  # noqa: E402 — placed here to avoid circular at module top
