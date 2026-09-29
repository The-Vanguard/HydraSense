"""
scripts/stage0/check_tier1_apis.py
Stage 0 — Data-Access Lockdown (HydraSense_Final.md §16.2)

Confirms live reachability of every Tier 1 data source before any pipeline
code is written.  Tier 1 = zero/low friction, scriptable, no approval wait
(Final.md §8.3):

  1. OpenTopography  — SRTM/GLO-30 DEM fetch
  2. ESA WorldCover  — S3 / Copernicus STAC catalog
  3. Open-Meteo      — free forecast API, no key required
  4. Nominatim       — geocoding / boundary resolution (OSM)

Exit codes:
  0 — all Tier 1 sources reachable
  1 — one or more Tier 1 sources unreachable (blocks Stage 1)

Usage:
  python scripts/stage0/check_tier1_apis.py
"""

from __future__ import annotations

import sys
import time
import urllib.request
import urllib.error
import json
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Test coordinates — Wayanad (demo shortlist anchor, Final.md §14.3)
# ---------------------------------------------------------------------------
TEST_LAT = 11.5448   # Mundakkai, Wayanad, Kerala
TEST_LON = 76.0836

TIMEOUT_SEC = 15      # per-request timeout — venue wifi is the known failure mode


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ApiCheckResult:
    name:        str
    url:         str
    reachable:   bool
    status_code: Optional[int] = None
    latency_ms:  Optional[float] = None
    error:       Optional[str] = None
    note:        str = ""


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = TIMEOUT_SEC) -> tuple[int, bytes]:
    """HTTP GET with timeout. Returns (status_code, body_bytes)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "HydraSense-Stage0-Check/1.0 "
                "(SIH2026; contact: hydrasense.sih2026@example.org)"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


# ---------------------------------------------------------------------------
# Individual probe functions
# ---------------------------------------------------------------------------

def check_opentopography() -> ApiCheckResult:
    """
    OpenTopography SRTM 30m DEM.
    Uses the /API/globaldem endpoint with a tiny 0.01°x0.01° bbox to confirm
    the API is reachable without downloading a large file.
    An API key is optional for small requests; we probe without one first.
    Docs: https://portal.opentopography.org/apidocs/
    """
    name = "OpenTopography (SRTM GLO-30 DEM)"
    url = (
        "https://portal.opentopography.org/API/globaldem"
        "?demtype=SRTMGL1"
        f"&south={TEST_LAT:.4f}&north={TEST_LAT + 0.01:.4f}"
        f"&west={TEST_LON:.4f}&east={TEST_LON + 0.01:.4f}"
        "&outputFormat=GTiff"
    )
    t0 = time.perf_counter()
    try:
        status, body = _get(url)
        latency = (time.perf_counter() - t0) * 1000
        if status == 200 and len(body) > 0:
            return ApiCheckResult(
                name, url, True, status, latency,
                note=f"Response {len(body):,} bytes — DEM tile confirmed",
            )
        return ApiCheckResult(name, url, False, status, latency,
                              error=f"Unexpected status {status}")
    except urllib.error.HTTPError as e:
        latency = (time.perf_counter() - t0) * 1000
        body_text = e.read().decode("utf-8", errors="replace")[:200]
        # 400 with an API-key message still means the server is responding
        if e.code == 400 and "API" in body_text.upper():
            return ApiCheckResult(
                name, url, True, e.code, latency,
                note="Server up — API key required for unrestricted access (free at opentopography.org)",
            )
        return ApiCheckResult(name, url, False, e.code, latency, error=str(e))
    except Exception as exc:
        latency = (time.perf_counter() - t0) * 1000
        return ApiCheckResult(name, url, False, None, latency, error=str(exc))


def check_esa_worldcover() -> ApiCheckResult:
    """
    ESA WorldCover 10m (2021) — Copernicus STAC endpoint.
    Probes the STAC collection root, a lightweight JSON response that confirms
    the service is reachable without downloading any raster tile.
    Full tiles fetched via S3 / Copernicus Data Space in Stage 1.
    Docs: https://worldcover2021.esa.int/
    """
    name = "ESA WorldCover (Copernicus STAC catalog)"
    url = (
        "https://services.terrascope.be/stac/collections/"
        "urn:eop:VITO:ESA_WorldCover_10m_2021_AWS_V2"
    )
    t0 = time.perf_counter()
    try:
        status, body = _get(url)
        latency = (time.perf_counter() - t0) * 1000
        data = json.loads(body)
        if status == 200 and "id" in data:
            return ApiCheckResult(
                name, url, True, status, latency,
                note=f"Collection ID: {data.get('id', '?')[:60]}",
            )
        return ApiCheckResult(name, url, False, status, latency,
                              error="Unexpected response structure")
    except Exception as exc:
        latency = (time.perf_counter() - t0) * 1000
        return ApiCheckResult(name, url, False, None, latency, error=str(exc))


def check_open_meteo() -> ApiCheckResult:
    """
    Open-Meteo — free forecast API, no key required (Final.md §8.3 Tier 1).
    Fetches a 1-day hourly rainfall forecast for the Wayanad test coordinate.
    Docs: https://open-meteo.com/en/docs
    """
    name = "Open-Meteo (forecast rainfall, no API key)"
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={TEST_LAT}&longitude={TEST_LON}"
        "&hourly=precipitation"
        "&forecast_days=1"
        "&timezone=Asia%2FKolkata"
    )
    t0 = time.perf_counter()
    try:
        status, body = _get(url)
        latency = (time.perf_counter() - t0) * 1000
        data = json.loads(body)
        hours = data.get("hourly", {}).get("precipitation", [])
        if status == 200 and len(hours) > 0:
            return ApiCheckResult(
                name, url, True, status, latency,
                note=f"{len(hours)} hourly forecast steps returned",
            )
        return ApiCheckResult(name, url, False, status, latency,
                              error="No precipitation data in response")
    except Exception as exc:
        latency = (time.perf_counter() - t0) * 1000
        return ApiCheckResult(name, url, False, None, latency, error=str(exc))


def check_nominatim() -> ApiCheckResult:
    """
    Nominatim — OSM geocoding / boundary resolution (Final.md §6 step 1).
    Queries 'Wayanad Kerala India' to confirm the endpoint is live.
    OSM usage policy requires a valid User-Agent (set in _get()).
    """
    name = "Nominatim (OSM geocoding / boundary resolve)"
    url = (
        "https://nominatim.openstreetmap.org/search"
        "?q=Wayanad+Kerala+India"
        "&format=json"
        "&limit=1"
        "&polygon_geojson=0"
    )
    t0 = time.perf_counter()
    try:
        status, body = _get(url)
        latency = (time.perf_counter() - t0) * 1000
        data = json.loads(body)
        if status == 200 and len(data) > 0:
            top = data[0]
            return ApiCheckResult(
                name, url, True, status, latency,
                note=f"Top result: {top.get('display_name', '?')[:70]}",
            )
        return ApiCheckResult(name, url, False, status, latency,
                              error="No results for 'Wayanad Kerala India'")
    except Exception as exc:
        latency = (time.perf_counter() - t0) * 1000
        return ApiCheckResult(name, url, False, None, latency, error=str(exc))


# ---------------------------------------------------------------------------
# Runner + reporting
# ---------------------------------------------------------------------------

CHECKS = [
    check_opentopography,
    check_esa_worldcover,
    check_open_meteo,
    check_nominatim,
]


def run_all() -> list[ApiCheckResult]:
    results: list[ApiCheckResult] = []
    for fn in CHECKS:
        label = fn.__doc__.strip().splitlines()[0].strip()
        print(f"  Checking {label} ...", end="", flush=True)
        r = fn()
        tag = "OK  " if r.reachable else "FAIL"
        ms  = f"{r.latency_ms:.0f}ms" if r.latency_ms is not None else "—"
        print(f" [{tag}]  {ms}")
        results.append(r)
    return results


def print_summary(results: list[ApiCheckResult]) -> None:
    print("\n" + "=" * 120)
    print("STAGE 0 — TIER 1 API REACHABILITY REPORT   (HydraSense_Final.md §16.2)")
    print("=" * 120)
    print(f"{'Source':<52} {'Status':<8} {'Latency':>8}  Note / Error")
    print("-" * 120)
    for r in results:
        status = "[LIVE]  " if r.reachable else "[FAIL]  "
        ms_str = f"{r.latency_ms:.0f} ms" if r.latency_ms is not None else "—"
        note   = r.note if r.reachable else (r.error or "")
        print(f"{r.name:<52} {status:<8} {ms_str:>8}  {note[:52]}")
    print("=" * 120)

    all_ok = all(r.reachable for r in results)
    if all_ok:
        print("\n[PASS]  ALL TIER 1 SOURCES REACHABLE")
        print("        Stage 1 (Autonomous Region Onboarding Pipeline) is UNBLOCKED.")
        print("        Next: run prefetch_soilgrids.py to pre-fetch bulk SoilGrids rasters.")
    else:
        failed = [r.name for r in results if not r.reachable]
        print(f"\n[FAIL]  {len(failed)} SOURCE(S) UNREACHABLE: {', '.join(failed)}")
        print("        Stage 1 is BLOCKED until all Tier 1 sources respond.")
        print("        Possible causes: network connectivity, API key requirement, service outage.")


if __name__ == "__main__":
    print("HydraSense Stage 0 — Tier 1 API Reachability Check")
    print(f"Reference: HydraSense_Final.md §8.3 / §16.2")
    print(f"Test anchor: {TEST_LAT}°N, {TEST_LON}°E (Mundakkai, Wayanad — demo shortlist)\n")
    results = run_all()
    print_summary(results)
    sys.exit(0 if all(r.reachable for r in results) else 1)
