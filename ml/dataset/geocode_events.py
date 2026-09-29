"""
ml/dataset/geocode_events.py -- Stage 4, step 1: give every historical event a location.

Reads   data/events/historical_events.csv        (57 graded real events, no coordinates)
Writes  data/events/historical_events_geocoded.csv
        data/events/geocode_cache.json           (raw Nominatim answers, so reruns are offline)

Method (v2 Sec. 8.4 / Gap Analysis 0.3): the `location` column is a comma list from most to least
specific ("village, block, district, state").  We try the most specific name first and fall back
to coarser names.  The level that matched sets a floor on position uncertainty, because a
district centroid is not a village.  A hit that lands outside the region's plausibility box is
rejected (namesake villages exist in other states).  Nothing is silently defaulted: an event
that cannot be placed is written with lat/lon empty and geocode_status = "FAILED".

Nominatim policy: <= 1 request/s, identifying User-Agent, results cached.
"""
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "events" / "historical_events.csv"
OUT = ROOT / "data" / "events" / "historical_events_geocoded.csv"
# Hand-verified coordinates (from a cited paper / agency report) override the geocoder.
# Columns: event_id,lat,lon,position_uncertainty_m,source_url,checked_by
OVERRIDES = ROOT / "data" / "events" / "event_coordinate_overrides.csv"
CACHE = ROOT / "data" / "events" / "geocode_cache.json"

URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "HydraSense-SIH26192-event-geocoder/1.0"}
TIMEOUT_S = 20

# Events located no better than this are region-level only (not hex labels).
HEX_ASSIGN_MAX_M = 5000
# If the most specific name could not be found, the match is a nearby/larger place: floor (m).
LEVEL_FLOOR_M = {0: 0, 1: 3000, 2: 10000, 3: 25000}
# Manual curation, each with a reason: events that are a linear stretch or multi-site cluster
# have no single-hex location, whatever the geocoder returns.
NOT_POINT_LIKE = {
    "NH29-2024-LS-01": "linear highway stretch Kohima-Dimapur (~75 km)",
    "BANASEPPA-2025-LS-01": "linear NH-13 stretch Bana-Seppa",
    "DIMAHASAO-2022-LS-01": "5178 slides over 11-18 May (multi-site cluster)",
    "NILGIRIS-2009-LS-01": "cluster of 70+ slides over three taluks",
    "KODAGU-2018-LS-01": "district-wide cluster",
    "BARAK-2020-LS-01": "three simultaneous slides in three districts",
    "KOOTTICKAL-2021-LS-01": "cluster of 4 slides in adjacent panchayats",
    "GAROHILLS-2024-LS-01": "slides in two districts",
    "SATARA-2021-LS-01": "multiple villages",
}

# QC-only plausibility boxes (lat_min, lat_max, lon_min, lon_max).  Used to REJECT wrong
# namesake matches; never used to set or move a coordinate.
REGION_BOX = {
    "Southern Western Ghats": (8.0, 13.0, 74.5, 77.6),
    "Northern Western Ghats": (14.5, 20.0, 72.5, 74.6),
    "Nilgiris-Anamalai-Palani": (9.8, 12.2, 76.0, 77.7),
    "Eastern Ghats": (13.0, 21.0, 78.0, 85.0),
    "Himachal Pradesh": (30.3, 33.3, 75.5, 79.1),
    "Jammu & Kashmir / Ladakh": (32.0, 36.0, 73.5, 80.5),
    "Uttarakhand": (28.7, 31.5, 77.5, 81.1),
    "Sikkim / Darjeeling": (26.3, 28.2, 87.9, 89.1),
    "Arunachal Pradesh": (26.6, 29.5, 91.5, 97.5),
    "Mizoram / Manipur / Nagaland": (22.0, 27.3, 92.2, 95.3),
    "Meghalaya / Assam hills": (24.0, 26.3, 89.7, 93.0),
}

# Events excluded from the rainfall-triggered training set (v2 Sec. 15.8.2 exclusion rule).
OUT_OF_SCOPE = {
    "CHAMOLI-2021-FF-01": "rock-ice avalanche trigger (not rainfall)",
    "SOUTHLHONAK-2023-FF-01": "glacial lake outburst (GLOF) trigger",
    "KEDARNATH-2013-FF-01": "mixed glacial-lake / debris-flow trigger",
}
# Kept, but the trigger is not purely natural rainfall.
FLAGGED = {
    "ANNAMAYYA-2021-FF-01": "dam breach after extreme rain",
    "TALACAUVERY-2020-LS-01": "date uncertain (5 vs 6 Aug)",
    "BARAGHARA-2018-LS-01": "date uncertain (11 vs 12 Oct)",
}


def candidates(location: str):
    """Yield (level, query) from most to least specific."""
    location = re.sub(r"\(.*?\)", "", location)      # drop parentheticals first
    parts = [p.strip() for p in re.split(r",", location) if p.strip()]
    # OSM does not know "J&K"; and generic admin words hurt matching ("Canacona taluka").
    parts = [re.sub(r"\bJ&K\b", "Jammu and Kashmir", p) for p in parts]
    parts = [re.sub(r"\b(taluka|taluk|tehsil|tehsils|tahsil|hamlet|block|subdivision)\b", "",
                    p, flags=re.I).strip() for p in parts]
    parts = [re.sub(r"\s{2,}", " ", p) for p in parts if p]
    n = len(parts)
    for i in range(n - 1):
        level = min(i, 3)
        head = parts[i]
        tail = ", ".join(parts[i + 1:])
        # a head like "A-B-C" or "A & B" is several names: try each
        subs = [s.strip() for s in re.split(r"\s*(?:->|[-&/])\s*|\s+and\s+", head) if s.strip()]
        for s in ([head] + subs if len(subs) > 1 else [head]):
            yield level, f"{s}, {tail}, India"
    # Looser fallback: each single name with only the state (last part), skipping the
    # intermediate parts.  Level = position in the list, so uncertainty is still inflated.
    state = parts[-1] if parts else ""
    for i in range(min(n - 1, 2)):
        yield min(i, 3), f"{parts[i]}, India"
    for i in range(n - 1):
        for s in [x.strip() for x in re.split(r"\s*[-&/]\s*|\s+and\s+|\s+incl\.?\s+", parts[i]) if x.strip()]:
            yield min(i, 3), f"{s}, {state}, India"


def query(q: str, cache: dict):
    if q in cache:
        return cache[q]
    time.sleep(1.1)
    try:
        r = requests.get(URL, params={"q": q, "format": "jsonv2", "limit": 3,
                                      "countrycodes": "in"}, headers=HEADERS, timeout=TIMEOUT_S)
        r.raise_for_status()
        res = r.json()
    except Exception as exc:  # network failure is recorded, not hidden
        print(f"  ! request failed for {q!r}: {exc}", file=sys.stderr)
        return None
    cache[q] = res
    return res


def halfdiag_m(hit):
    """Half the diagonal of the matched OSM feature's bounding box (m).  A village node is
    a few hundred metres; a district is tens of km.  This is the honest floor on where the
    event actually was, given only that the name matched."""
    try:
        s_, n_, w_, e_ = (float(x) for x in hit["boundingbox"])
    except (KeyError, ValueError):
        return None
    import math
    dy = (n_ - s_) * 111_000
    dx = (e_ - w_) * 111_000 * math.cos(math.radians((n_ + s_) / 2))
    return round(0.5 * math.hypot(dx, dy))


def in_box(lat, lon, box):
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def geocode_row(row, cache):
    box = REGION_BOX[row["region"]]
    tried = 0
    for level, q in candidates(row["location"]):
        res = query(q, cache)
        tried += 1
        if not res:
            continue
        for hit in res:
            lat, lon = float(hit["lat"]), float(hit["lon"])
            if in_box(lat, lon, box):
                return dict(lat=lat, lon=lon, geocode_query=q, geocode_level=level,
                            feature_halfdiag_m=halfdiag_m(hit),
                            geocode_type=f"{hit.get('category','')}/{hit.get('type','')}",
                            geocode_display=hit.get("display_name", "")[:160],
                            geocode_status="OK" if level == 0 else "COARSE")
    return dict(lat=None, lon=None, geocode_query="", geocode_level=None,
                feature_halfdiag_m=None, geocode_type="",
                geocode_display="", geocode_status="FAILED")


def main():
    df = pd.read_csv(SRC)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows = []
    for _, r in df.iterrows():
        g = geocode_row(r, cache)
        CACHE.write_text(json.dumps(cache, indent=1))
        rows.append(g)
        print(f"{r['event_id']:26s} {g['geocode_status']:7s} "
              f"{g['lat']} {g['lon']}  L{g['geocode_level']}")
    g = pd.DataFrame(rows)
    out = pd.concat([df, g], axis=1)
    if OVERRIDES.exists():
        ov = pd.read_csv(OVERRIDES).dropna(subset=["lat", "lon"])
        for _, o in ov.iterrows():
            m = out["event_id"] == o["event_id"]
            if not m.any():
                print(f"  ! override for unknown event {o['event_id']}", file=sys.stderr)
                continue
            out.loc[m, ["lat", "lon"]] = [float(o["lat"]), float(o["lon"])]
            out.loc[m, "feature_halfdiag_m"] = float(o["position_uncertainty_m"])
            out.loc[m, "geocode_level"] = 0
            out.loc[m, "geocode_status"] = "MANUAL"
            out.loc[m, "geocode_query"] = str(o["source_url"])
        print(f"applied {len(ov)} manual coordinate overrides")
    out["scope_note"] = out["event_id"].map({**FLAGGED, **OUT_OF_SCOPE}).fillna("")
    # final uncertainty = max(source-reported, matched-feature half-diagonal, 500 m floor)
    out["position_uncertainty_m_final"] = pd.concat(
        [out["position_uncertainty_m"], out["feature_halfdiag_m"]], axis=1).max(axis=1)
    floor = out["geocode_level"].map(lambda l: LEVEL_FLOOR_M[int(l)] if pd.notna(l) else None)
    out["position_uncertainty_m_final"] = pd.concat(
        [out["position_uncertainty_m_final"], floor], axis=1).max(axis=1)
    out.loc[out["lat"].isna(), "position_uncertainty_m_final"] = None
    # H3 res-8 cells are ~0.9 km across: only place an event in one cell if we know where
    # it was to within ~5 km; otherwise it stays region-level (not used to label a hex).
    out["hex_assignable"] = (out["position_uncertainty_m_final"] <= HEX_ASSIGN_MAX_M) \
        & ~out["event_id"].isin(NOT_POINT_LIKE)
    out["scope_note"] = out.apply(
        lambda r: "; ".join(x for x in [r["scope_note"], NOT_POINT_LIKE.get(r["event_id"], "")] if x), axis=1)
    out["in_scope"] = ~out["event_id"].isin(OUT_OF_SCOPE)
    out.to_csv(OUT, index=False)
    print("\nstatus counts:", out["geocode_status"].value_counts().to_dict())
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
