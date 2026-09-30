"""
backend/onboarding/dem.py
Step 2 of the Autonomous Region Onboarding Pipeline (Final.md §6, step 2 / §8.3).

Fetches a Digital Elevation Model (DEM) GeoTIFF for any bounding box from
OpenTopography (SRTM GL1, 1 arc-second ≈ 30m resolution).

Final.md §8.3 Tier 1: OpenTopography — always attempted live first.
Fallback (§14.4): if OpenTopography is unreachable or returns an error, the
caller is given a DemResult with success=False and a descriptive error; the
pipeline marks terrain source as "unavailable" and blocks FS computation for
that region until a DEM is available.

API key: OpenTopography requires a free API key for unrestricted access.
  Set environment variable: OPENTOPOGRAPHY_API_KEY=<your_key>
  Free registration: https://portal.opentopography.org/requestApiKey

DEM types supported (ordered by preference):
  SRTMGL1   — SRTM 1 arc-second global (~30m), broad coverage
  COP90     — Copernicus GLO-90 (~90m), fallback if GLO-30 is unavailable
"""

from __future__ import annotations

import os
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT     = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "terrain"

OPENTOPO_BASE = "https://portal.opentopography.org/API/globaldem"
USER_AGENT    = "HydraSense/1.0 (SIH2026; hydrasense.sih2026@example.org)"
TIMEOUT_SEC   = 90    # DEM downloads can be large

# Buffer to ensure DEM covers a margin beyond the bbox
# (terrain derivatives near the edge of the bbox need surrounding context)
BBOX_BUFFER_DEG = 0.05   # ~5.5 km margin at equator


@dataclass
class DemResult:
    region_code: str
    success:     bool
    dem_path:    Optional[Path] = None
    dem_type:    str = ""            # "SRTMGL1" | "COP90"
    latency_s:   float = 0.0
    source:      str = ""            # "live" | "cached" | "unavailable"
    error:       Optional[str] = None
    bbox_used:   dict = field(default_factory=dict)


def _api_key() -> str:
    key = os.environ.get("OPENTOPOGRAPHY_API_KEY", "")
    return key


def _dem_path(region_code: str, dem_type: str) -> Path:
    return DATA_DIR / region_code / f"dem_{dem_type.lower()}_{region_code}.tif"


def _fetch_dem(
    region_code: str,
    bbox: dict,
    dem_type: str = "SRTMGL1",
) -> DemResult:
    """
    Download a DEM GeoTIFF for the given bbox.
    Applies a BBOX_BUFFER_DEG margin to ensure edge terrain derivatives are stable.
    """
    out_path = _dem_path(region_code, dem_type)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Expand bbox with buffer
    south = bbox["south"] - BBOX_BUFFER_DEG
    north = bbox["north"] + BBOX_BUFFER_DEG
    west  = bbox["west"]  - BBOX_BUFFER_DEG
    east  = bbox["east"]  + BBOX_BUFFER_DEG
    bbox_used = {"south": south, "north": north, "west": west, "east": east}

    # Use cached if already downloaded
    if out_path.exists() and out_path.stat().st_size > 1024:
        return DemResult(
            region_code=region_code, success=True,
            dem_path=out_path, dem_type=dem_type,
            source="cached", bbox_used=bbox_used,
        )

    params = {
        "demtype":      dem_type,
        "south":        f"{south:.5f}",
        "north":        f"{north:.5f}",
        "west":         f"{west:.5f}",
        "east":         f"{east:.5f}",
        "outputFormat": "GTiff",
    }
    api_key = _api_key()
    if api_key:
        params["API_Key"] = api_key

    url = f"{OPENTOPO_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            body = resp.read()
            latency = time.perf_counter() - t0

        # Validate GeoTIFF magic bytes (II=little-endian or MM=big-endian TIFF)
        if len(body) < 100 or body[:2] not in (b"II", b"MM"):
            err_text = body[:300].decode("utf-8", errors="replace")
            return DemResult(
                region_code=region_code, success=False, dem_type=dem_type,
                latency_s=latency, source="live",
                error=f"Response is not a valid GeoTIFF: {err_text[:120]}",
                bbox_used=bbox_used,
            )

        out_path.write_bytes(body)
        return DemResult(
            region_code=region_code, success=True,
            dem_path=out_path, dem_type=dem_type,
            latency_s=latency, source="live", bbox_used=bbox_used,
        )

    except urllib.error.HTTPError as e:
        latency = time.perf_counter() - t0
        body_text = e.read().decode("utf-8", errors="replace")[:200]
        error_msg = f"HTTP {e.code}: {body_text}"
        # 401 = no API key; 400 = bad bbox; both are recoverable with fix
        return DemResult(
            region_code=region_code, success=False, dem_type=dem_type,
            latency_s=latency, source="live",
            error=error_msg, bbox_used=bbox_used,
        )
    except Exception as exc:
        latency = time.perf_counter() - t0
        return DemResult(
            region_code=region_code, success=False, dem_type=dem_type,
            latency_s=latency, source="unavailable",
            error=str(exc), bbox_used=bbox_used,
        )


def fetch_dem_for_region(region_code: str, bbox: dict) -> DemResult:
    """
    Public entry point. Tries SRTMGL1, then COP30 (Copernicus GLO-30), then COP90.
    Returns the first successful DemResult, or the last failure if both fail.
    """
    # COP30 = Copernicus GLO-30; it can be staged without a key by scripts/stage0/fetch_cop30_dem.py
    for dem_type in ("SRTMGL1", "COP30", "COP90"):
        result = _fetch_dem(region_code, bbox, dem_type=dem_type)
        if result.success:
            print(f"    DEM ({dem_type}): {result.source} — {result.dem_path.name}")
            return result
        print(f"    DEM ({dem_type}): FAIL — {result.error[:80] if result.error else 'unknown'}")

    # Both failed — return the last result with source="unavailable"
    result.source = "unavailable"
    return result
