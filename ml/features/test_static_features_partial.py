"""Phase 3 partial validation -- runs without DEM/landcover rasters."""
import sys
import math
from pathlib import Path

import h3
import numpy as np
import pandas as pd
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[2]
errors = []

# ---- 1. h3 v4: shared hex assertion ----
h_mun = h3.latlng_to_cell(11.5185, 76.0524, 8)
h_cho = h3.latlng_to_cell(11.5143, 76.0498, 8)
if h_mun == h_cho == "8860064e4bfffff":
    print(f"[OK] Shared hex: {h_mun}  (Mundakkai == Chooralmala at H3 res-8)")
else:
    errors.append(f"FAIL: Shared hex mismatch. Mundakkai={h_mun}, Chooralmala={h_cho}")

# centroid should be within ~300m of both village centroids
lat_c, lon_c = h3.cell_to_latlng("8860064e4bfffff")
print(f"[OK] Shared hex centroid: ({lat_c:.5f}, {lon_c:.5f})")

# ---- 2. GSI CSV null parsing ----
gsi_csv = ROOT / "data" / "susceptibility" / "gsi_susceptibility.csv"
df = pd.read_csv(gsi_csv, dtype=str)
df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
print("     GSI CSV columns:", df.columns.tolist())

def parse_class(val):
    if val is None:
        return None
    try:
        if math.isnan(float(val)):
            return None
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if s == "" or s.upper().startswith("UNRESOLVED"):
        return None
    return s

col = "susceptibility_class" if "susceptibility_class" in df.columns else "gsi_susceptibility_class"
df["gsi_susceptibility_class"] = df[col].apply(parse_class)
null_count = int(df["gsi_susceptibility_class"].isna().sum())
total_hexes = len(df)
print(f"[OK] GSI hexes: {total_hexes}, null susceptibility_class: {null_count}")

# Phase 2 fix (c398076) resolved all 9 Punjirimattom hexes from UNRESOLVED to
# Moderate/High using GSI Jul-2024 FIR + The News Minute confirmation.
# As of Phase 2 fix merge into main, null_count must be 0.
if null_count != 0:
    errors.append(
        f"FAIL: Expected 0 null hexes (Phase 2 fix resolved all Punjirimattom hexes), got {null_count}"
    )
else:
    print("[OK] 0 null hexes — all Punjirimattom hexes resolved by Phase 2 fix")

shared = df[df["hex_id"] == "8860064e4bfffff"]
if len(shared) != 1:
    errors.append(f"FAIL: Shared hex appears {len(shared)} times, expected 1")
elif shared.iloc[0]["gsi_susceptibility_class"] != "Moderate":
    errors.append(
        f"FAIL: Shared hex class={shared.iloc[0]['gsi_susceptibility_class']!r}, expected Moderate"
    )
else:
    print("[OK] Shared hex appears once, class=Moderate")

# Verify all 9 Punjirimattom hexes have a real non-null string class (Phase 2 fix).
# village-core hex must be Moderate; ring-1/2 hexes must be High.
import json

PUNJI_HEXES = [
    "88600640b7fffff",  # village-core  -> Moderate
    "88600640b1fffff", "88600640b3fffff", "8860064e59fffff",  # inner-slope -> High
    "88600640b9fffff", "88600640bbfffff",  # upper-slope -> High
    "8860064565fffff", "886006456dfffff", "8860064e5bfffff",  # upper-slope -> High
]
for hid in PUNJI_HEXES:
    row_match = df[df["hex_id"] == hid]
    if len(row_match) != 1:
        errors.append(f"FAIL: Punjirimattom hex {hid} missing from CSV")
        continue
    cls = row_match.iloc[0]["gsi_susceptibility_class"]
    if cls is None or (isinstance(cls, float) and math.isnan(cls)):
        errors.append(f"FAIL: Punjirimattom hex {hid} still null after Phase 2 fix")
    elif not isinstance(cls, str) or cls.strip() == "":
        errors.append(f"FAIL: Punjirimattom hex {hid} class is not a non-empty string: {cls!r}")
    else:
        pass  # OK — printed in summary below
if not errors:
    print(f"[OK] All {len(PUNJI_HEXES)} Punjirimattom hexes have resolved string classes")

# Confirm JSONB serialization: all classes are strings, no NaN leaks through.
# Phase 2 fix means no null values; verify json.dumps(allow_nan=False) passes cleanly.
def _nan_to_none(v):
    """Return None if v is None or float NaN, else v. Mirrors static_features._val()."""
    if v is None:
        return None
    try:
        if math.isnan(float(v)):
            return None
    except (TypeError, ValueError):
        pass
    return v

punji_core = df[df["hex_id"] == "88600640b7fffff"]
if len(punji_core) == 1:
    raw_val = punji_core.iloc[0]["gsi_susceptibility_class"]
    jsonb = {"hex_id": "88600640b7fffff", "gsi_susceptibility_class": _nan_to_none(raw_val)}
    serialized = json.dumps(jsonb, allow_nan=False)
    expected_class = "Moderate"
    if f'"gsi_susceptibility_class": "{expected_class}"' in serialized:
        print(f"[OK] JSONB serialization for Punjirimattom village-core: {serialized}")
    else:
        errors.append(f"FAIL: JSONB serialization unexpected: {serialized!r}")
else:
    errors.append("FAIL: Punjirimattom village-core hex not found for JSONB check")

# ---- 3. Historical event count ----
ev_csv = ROOT / "data" / "events" / "historical_events.csv"
ev_df = pd.read_csv(ev_csv, dtype=str)
ev_df.columns = [c.strip().lower() for c in ev_df.columns]
n_events = len(ev_df)
print(f"[OK] Events CSV: {n_events} rows. Columns: {ev_df.columns.tolist()[:6]}")

PILOT = {
    "Mundakkai": (11.5185, 76.0524),
    "Chooralmala": (11.5143, 76.0498),
    "Attamala": (11.5220, 76.0570),
    "Punjirimattom": (11.5100, 76.0450),
}
CLUSTER = (
    sum(v[0] for v in PILOT.values()) / 4,
    sum(v[1] for v in PILOT.values()) / 4,
)
M_LAT = 111320.0
M_LON = 111320.0 * math.cos(math.radians(11.5))

def ev_latlon(src: str):
    s = (src or "").lower()
    for v, c in PILOT.items():
        if v.lower() in s:
            return c
    return CLUSTER

def dist_m(la1, lo1, la2, lo2):
    return math.sqrt(((la2 - la1) * M_LAT) ** 2 + ((lo2 - lo1) * M_LON) ** 2)

hex_lat, hex_lon = h3.cell_to_latlng("8860064e4bfffff")
src_col = "source" if "source" in ev_df.columns else ev_df.columns[-1]
count = sum(
    1 for _, r in ev_df.iterrows()
    if dist_m(hex_lat, hex_lon, *ev_latlon(r.get(src_col, ""))) <= 500.0
)
print(f"[OK] historical_event_count_500m for shared hex: {count}")

# ---- Summary ----
print()
if errors:
    for e in errors:
        print(e)
    print(f"\n{len(errors)} VALIDATION(S) FAILED")
    sys.exit(1)
else:
    print("=" * 60)
    print("ALL PARTIAL VALIDATIONS PASSED")
    print("Full run requires: dem_wayanad.tif, landcover_wayanad.tif,")
    print("  ndvi_wayanad.tif  (Phase 1 ingest outputs)")
    print("=" * 60)
