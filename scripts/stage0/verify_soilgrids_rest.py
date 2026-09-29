"""
scripts/stage0/verify_soilgrids_rest.py
Stage 0 — Data-Access Lockdown (HydraSense_Final.md §16.2 / §7.3 / §8.2)

Re-checks SoilGrids REST point-query API status before locking in the
WCS/GEE bulk-pre-fetch workaround.

Final.md §7.3 (verified fact):
    "ISRIC's SoilGrids REST point-query API is officially paused with no
     published restoration date (confirmed directly from ISRIC's own status
     notice, not assumed)."

This script checks THREE endpoints:
  1. SoilGrids REST point-query API  — the paused one (may have been restored)
  2. SoilGrids WCS (OGC Web Coverage Service) — the bulk-raster alternative
  3. ISRIC status page               — to see if there is a restoration notice

Decision logic (per Final.md §16.2):
  - If REST is restored AND returns valid data → update data-availability
    matrix (§8.2) and remove the WCS-only workaround note.
  - If REST is still paused → confirm WCS path is accessible; prefetch_soilgrids.py
    will use WCS.

Exit codes:
  0 — at least one SoilGrids access path (REST or WCS) is functional
  1 — all SoilGrids paths unreachable (fatal for Stage 2 physics layer)

Usage:
  python scripts/stage0/verify_soilgrids_rest.py
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
# Test coordinate — Wayanad anchor
# ---------------------------------------------------------------------------
TEST_LAT = 11.5448
TEST_LON = 76.0836

TIMEOUT_SEC = 20   # SoilGrids can be slow even when healthy

UA = "HydraSense-Stage0-Check/1.0 (SIH2026; contact: hydrasense.sih2026@example.org)"


@dataclass
class SoilCheckResult:
    name:      str
    url:       str
    reachable: bool
    status:    Optional[int] = None
    latency:   Optional[float] = None
    note:      str = ""
    error:     Optional[str] = None


def _get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
        return r.status, r.read()


# ---------------------------------------------------------------------------
# 1. SoilGrids REST point-query API (paused per Final.md §7.3)
# ---------------------------------------------------------------------------
def check_soilgrids_rest() -> SoilCheckResult:
    """
    SoilGrids REST point-query (https://rest.soilgrids.org/soilgrids/v2.0).
    Final.md §7.3 states this is paused. We check anyway — if it has been
    restored, Final.md §8.2's data-availability matrix should be revised.
    """
    name = "SoilGrids REST point-query API"
    url  = (
        "https://rest.soilgrids.org/soilgrids/v2.0/properties/query"
        f"?lon={TEST_LON}&lat={TEST_LAT}"
        "&property=clay&property=sand&property=bdod"
        "&depth=0-5cm&value=mean"
    )
    t0 = time.perf_counter()
    try:
        status, body = _get(url)
        ms = (time.perf_counter() - t0) * 1000
        data = json.loads(body)
        # A healthy response has a "properties" key with actual values
        if status == 200 and "properties" in data:
            return SoilCheckResult(
                name, url, True, status, ms,
                note="REST API RESTORED — update Final.md §8.2 data-availability matrix",
            )
        return SoilCheckResult(name, url, False, status, ms,
                               error=f"Unexpected response: {str(data)[:100]}")
    except urllib.error.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        body_text = e.read().decode("utf-8", errors="replace")[:300]
        if e.code in (503, 404, 410, 302):
            return SoilCheckResult(
                name, url, False, e.code, ms,
                note="Still paused/unavailable (consistent with Final.md §7.3)",
                error=f"HTTP {e.code}: {body_text[:120]}",
            )
        return SoilCheckResult(name, url, False, e.code, ms,
                               error=f"HTTP {e.code}: {body_text[:120]}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return SoilCheckResult(name, url, False, None, ms,
                               note="Likely still paused or DNS-unreachable",
                               error=str(exc))


# ---------------------------------------------------------------------------
# 2. SoilGrids WCS (OGC Web Coverage Service) — the working bulk-fetch path
# ---------------------------------------------------------------------------
def check_soilgrids_wcs() -> SoilCheckResult:
    """
    SoilGrids WCS GetCapabilities — confirms bulk raster download path is alive.
    This is the access method prefetch_soilgrids.py will use (Final.md §8.2).
    Docs: https://maps.isric.org/mapserv?map=/map/clay.map&SERVICE=WCS
    """
    name = "SoilGrids WCS (bulk raster — the working path)"
    url  = (
        "https://maps.isric.org/mapserv"
        "?map=/map/clay.map"
        "&SERVICE=WCS"
        "&VERSION=2.0.1"
        "&REQUEST=GetCapabilities"
    )
    t0 = time.perf_counter()
    try:
        status, body = _get(url)
        ms = (time.perf_counter() - t0) * 1000
        body_str = body.decode("utf-8", errors="replace")
        # GetCapabilities returns XML; a healthy response contains WCS_Capabilities or CoverageDescription
        if status == 200 and ("WCS_Capabilities" in body_str or "Capabilities" in body_str):
            # Count coverage IDs as a basic sanity check
            coverage_count = body_str.count("<wcs:Identifier>") + body_str.count("<ows:Identifier>")
            return SoilCheckResult(
                name, url, True, status, ms,
                note=f"WCS live — ~{coverage_count} coverage identifiers in capabilities doc",
            )
        return SoilCheckResult(name, url, False, status, ms,
                               error=f"Unexpected response (status {status})")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return SoilCheckResult(name, url, False, None, ms, error=str(exc))


# ---------------------------------------------------------------------------
# 3. ISRIC status/info page
# ---------------------------------------------------------------------------
def check_isric_status() -> SoilCheckResult:
    """
    ISRIC data service info page — check for any restoration announcement.
    Not a data endpoint; just confirms the web presence is reachable so we
    can manually check for status updates.
    """
    name = "ISRIC data service info page"
    url  = "https://www.isric.org/explore/soilgrids"
    t0   = time.perf_counter()
    try:
        status, body = _get(url)
        ms = (time.perf_counter() - t0) * 1000
        body_str = body.decode("utf-8", errors="replace").lower()
        if status == 200:
            # Very rough check for a restoration or pause notice
            if "unavailable" in body_str or "paused" in body_str or "maintenance" in body_str:
                note = "⚠  Page content mentions unavailability/maintenance — REST still paused"
            else:
                note = "Page accessible — check manually for REST restoration notice"
            return SoilCheckResult(name, url, True, status, ms, note=note)
        return SoilCheckResult(name, url, False, status, ms,
                               error=f"HTTP {status}")
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return SoilCheckResult(name, url, False, None, ms, error=str(exc))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CHECKS = [check_soilgrids_rest, check_soilgrids_wcs, check_isric_status]


def run() -> None:
    print("HydraSense Stage 0 — SoilGrids Access Path Verification")
    print("Reference: HydraSense_Final.md §7.3 / §8.2 / §16.2\n")

    results: list[SoilCheckResult] = []
    for fn in CHECKS:
        label = fn.__doc__.strip().splitlines()[0].strip()
        print(f"  Checking {label} ...", end="", flush=True)
        r = fn()
        tag = "OK  " if r.reachable else "FAIL"
        ms  = f"{r.latency:.0f}ms" if r.latency is not None else "—"
        print(f" [{tag}]  {ms}")
        results.append(r)

    print("\n" + "=" * 110)
    print("SOILGRIDS ACCESS PATH REPORT")
    print("=" * 110)
    for r in results:
        status = "✅ LIVE " if r.reachable else "❌ FAIL "
        ms_str = f"{r.latency:.0f} ms" if r.latency is not None else "—"
        print(f"{r.name:<45} {status}  {ms_str:>8}  {r.note[:55]}")
        if r.error and not r.reachable:
            print(f"  {'':45}           Error: {r.error[:70]}")
    print("=" * 110)

    rest_ok = results[0].reachable
    wcs_ok  = results[1].reachable

    print()
    if rest_ok:
        print("🔔  ACTION REQUIRED: SoilGrids REST API is responding.")
        print("    → Revise Final.md §8.2 data-availability matrix (REST column: Yes)")
        print("    → prefetch_soilgrids.py can use REST instead of WCS if preferred")
    elif wcs_ok:
        print("✅  SoilGrids REST is still paused (consistent with Final.md §7.3).")
        print("    WCS path is LIVE — prefetch_soilgrids.py will use WCS. No action needed.")
        print("    Next: run prefetch_soilgrids.py to fetch rasters for demo shortlist.")
    else:
        print("❌  BOTH SoilGrids REST and WCS are unreachable.")
        print("    Stage 2 physics layer (FS parameter derivation) is BLOCKED.")
        print("    Fallback: use hardcoded Wayanad parameters from Scientific Reports")
        print("    paper for the demo shortlist, but label as 'terrain-only estimate'.")

    sys.exit(0 if (rest_ok or wcs_ok) else 1)


if __name__ == "__main__":
    run()
