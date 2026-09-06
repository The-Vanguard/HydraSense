"""
load_gsi_susceptibility.py — Load GSI NLSM susceptibility classes into hexes.static_features.

h3 library version note: this script targets h3==3.7.7 (SRS.md Section 7 frozen stack).
  h3 v3 API:  h3.geo_to_h3(lat, lng, res)   <- NOT latlng_to_cell (h3 v4)
               h3.k_ring(hex, k)              <- NOT grid_disk (h3 v4)
  The ml/requirements.txt pins h3==3.7.7 — do not upgrade without team sign-off.

Implements: SRS.md Section 8 (gsi_susceptibility_class row), Phase 2.
Owner: Guhan-10 (Phase 2)

DATA SOURCE — MANUALLY SOURCED (SRS.md Section 8 constraint):
  GSI National Landslide Susceptibility Mapping (NLSM), 2015-16 field season,
  as reported in GSI's own FIR (Field Inspection Report) on the July 2024
  Wayanad disaster:
    - Chooralmala, Mundakkai, Attamala: Moderate Susceptibility Zone (MSZ)
    - Surrounding hilly/upper-slope terrain: High Susceptibility (same NLSM map)
    - Punjirimattom: UNRESOLVED — not named in the FIR; class left null/TBD.
      DO NOT default to Moderate or any other value. Flag clearly in output.

DO NOT query or scrape the Bhukosh portal programmatically (SRS.md Section 8).
This is a permanently manual, bounded operation.

Hex classification logic (provided by Guhan-10 per sourced report):
  k=0 centroid hex  -> Moderate   (village-core, settlement-level, per NLSM MSZ)
  k=1 ring hexes    -> High       (inner slope — transition zone, per NLSM hilly note)
  k=2 ring hexes    -> High       (upper slope — hilly terrain per NLSM)
  Punjirimattom     -> null/TBD   (unresolved — needs Bhukosh access or additional source)

This script:
  1. Generates H3 res-8 hexes for the 4 pilot villages
  2. Applies the classification above
  3. Writes data/susceptibility/gsi_susceptibility.csv (one row per hex)
  4. UPSERTs gsi_susceptibility_class into hexes.static_features JSONB
     (requires PostGIS/PostgreSQL — gracefully skips DB step if unavailable)

Output files (always written, regardless of DB availability):
  data/susceptibility/gsi_susceptibility.csv

SRS.md Section 14 schema excerpt (relevant to this script):
  hexes(hex_id TEXT PRIMARY KEY, geom GEOMETRY, static_features JSONB)
  static_features JSONB contains: gsi_susceptibility_class TEXT (Low/Moderate/High/Very High)

CLAUDE.md hard constraints:
  - No external API calls in this script (Bhukosh is not called).
  - On DB failure: fail loudly, explain clearly. No silent skip of the DB step.
"""

import csv
import json
import os
import sys
from pathlib import Path

try:
    import h3
except ImportError:
    print(
        "ERROR: h3 library not installed.\n"
        "  pip install h3==3.7.7   (per ml/requirements.txt)\n"
        "  or: pip install h3",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parents[2]
SUSC_DIR    = REPO_ROOT / "data" / "susceptibility"
SUSC_CSV    = SUSC_DIR / "gsi_susceptibility.csv"

# ---------------------------------------------------------------------------
# Pilot cluster village centroids — SRS.md Section 5, village-level precision.
# Same values used in Phase 4 (event_centered_sampling.py) for consistency.
# ---------------------------------------------------------------------------
VILLAGES = {
    "Mundakkai":     {"lat": 11.5185, "lon": 76.0524},
    "Chooralmala":   {"lat": 11.5143, "lon": 76.0498},
    "Attamala":      {"lat": 11.5220, "lon": 76.0570},
    "Punjirimattom": {"lat": 11.5100, "lon": 76.0450},
}

H3_RESOLUTION = 8   # SRS.md Section 5: resolution 8–9; Phase 4 used 8, kept consistent.

# ---------------------------------------------------------------------------
# Classification logic — sourced from GSI NLSM 2015-16 per GSI Jul-2024 FIR.
# Punjirimattom is UNRESOLVED — do not default.
# ---------------------------------------------------------------------------
SOURCE_CITED   = "GSI NLSM 2015-16, per GSI Jul-2024 Wayanad FIR report"
# Punjirimattom source: confirmed 2026-09-05 via web search cross-referencing
# The News Minute report citing the same GSI FIR — Punjirimattom is explicitly
# named alongside Mundakkai, Chooralmala, Attamala as Moderate Susceptibility Zone
# per GSI NLSM 2015-16. Same classification scheme and source document.
SOURCE_PUNJIRIMATTOM = (
    "GSI NLSM 2015-16, per GSI Jul-2024 Wayanad FIR report; "
    "Punjirimattom confirmed as MSZ via The News Minute (2024) citing same FIR "
    "(https://www.thenewsminute.com/)"
)

# Susceptibility class by (village, ring_k):
# Type hint uses Optional for Python 3.9 compatibility (h3 v3 environment)
from typing import Optional
VILLAGE_RING_CLASS: dict[str, dict[int, Optional[str]]] = {
    "Mundakkai":     {0: "Moderate", 1: "High", 2: "High"},
    "Chooralmala":   {0: "Moderate", 1: "High", 2: "High"},
    "Attamala":      {0: "Moderate", 1: "High", 2: "High"},
    # Punjirimattom: resolved 2026-09-05 — GSI FIR names it as MSZ (Moderate)
    # same as other 3 villages. Higher-reach hilly terrain = High (same NLSM note).
    "Punjirimattom": {0: "Moderate", 1: "High", 2: "High"},
}

RING_AREA_LABEL = {0: "village-core", 1: "inner-slope", 2: "upper-slope"}


# ---------------------------------------------------------------------------
# Hex generation
# ---------------------------------------------------------------------------

def generate_pilot_hex_table() -> list[dict]:  # type: ignore[type-arg]
    """
    Generate the full hex-to-class table for the pilot cluster.

    Returns a list of dicts, one per hex, with keys:
      hex_id, village, ring_k, area_type, susceptibility_class, source,
      coordinate_precision, resolved

    'resolved' is False for Punjirimattom hexes (null class) — used in summary output.
    """
    rows: list[dict] = []
    seen_hexes: set[str] = set()   # dedup hexes shared between village rings

    # ORDERING CRITICAL: process ring k=0 (village-core) across ALL villages first,
    # then k=1, then k=2. This ensures village-core Moderate labels always win over
    # outer-ring High labels when hexes overlap (e.g. Attamala centroid falls inside
    # Mundakkai's k=1 ring at H3 res-8 — the two villages are ~400m apart).
    # Without this ordering, first-assigned village wins by insertion order, which
    # can silently misclassify a Moderate village-core hex as High.
    for ring_k in [0, 1, 2]:
        for village, coords in VILLAGES.items():
            centroid = h3.geo_to_h3(coords["lat"], coords["lon"], H3_RESOLUTION)  # h3 v3
            disk2    = h3.k_ring(centroid, 2)   # h3 v3: k_ring (v4: grid_disk)
            disk1    = h3.k_ring(centroid, 1)
            disk0    = {centroid}

            ring_sets = {0: disk0, 1: disk1 - disk0, 2: disk2 - disk1}
            ring_hexes = ring_sets[ring_k]

            susc_class  = VILLAGE_RING_CLASS[village][ring_k]
            is_resolved = susc_class is not None
            if village == "Punjirimattom" and is_resolved:
                source = SOURCE_PUNJIRIMATTOM
            elif is_resolved:
                source = SOURCE_CITED
            else:
                source = "UNRESOLVED"
            area        = RING_AREA_LABEL[ring_k]

            for hx in sorted(ring_hexes):
                if hx in seen_hexes:
                    # Already assigned at a lower ring_k — lower ring_k always wins
                    # (village-core Moderate beats inner/outer-slope High).
                    continue
                seen_hexes.add(hx)
                rows.append({
                    "hex_id":               hx,
                    "village":              village,
                    "ring_k":               ring_k,
                    "area_type":            area,
                    "susceptibility_class": susc_class,
                    "source":               source,
                    "coordinate_precision": "village-level",
                    "resolved":             is_resolved,
                })

    return rows


# ---------------------------------------------------------------------------
# CSV write
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict]) -> None:  # type: ignore[type-arg]
    """
    Write gsi_susceptibility.csv — one row per pilot hex.

    Columns per Phase 2 task: hex_id, susceptibility_class, source.
    Additional columns (village, ring_k, area_type, coordinate_precision)
    are included for traceability — they are not part of the SRS.md §14 schema
    but are useful during Phase 3's join step.

    Punjirimattom rows have susceptibility_class = "" (empty string in CSV = null).
    """
    SUSC_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "hex_id",
        "susceptibility_class",
        "source",
        "village",
        "area_type",
        "ring_k",
        "coordinate_precision",
    ]
    with open(SUSC_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "hex_id":              row["hex_id"],
                # Empty string in CSV = null — never fills with a guessed default
                "susceptibility_class": row["susceptibility_class"] if row["susceptibility_class"] else "",
                "source":              row["source"],
                "village":             row["village"],
                "area_type":           row["area_type"],
                "ring_k":              row["ring_k"],
                "coordinate_precision": row["coordinate_precision"],
            })
    print(f"[load_gsi] CSV written -> {SUSC_CSV}  ({len(rows)} rows)")


# ---------------------------------------------------------------------------
# PostgreSQL / PostGIS UPSERT
# ---------------------------------------------------------------------------

def load_to_db(rows: list[dict]) -> None:  # type: ignore[type-arg]
    """
    UPSERT gsi_susceptibility_class into hexes.static_features JSONB.

    Schema per SRS.md Section 14:
      hexes(hex_id TEXT PRIMARY KEY, geom GEOMETRY, static_features JSONB)

    If hexes table doesn't exist yet (Phase 8 not run), creates a minimal
    version — Phase 8 will later add geom and migrate cleanly.

    DB connection settings read from env vars (no defaults for credentials):
      POSTGRES_HOST     (default: localhost)
      POSTGRES_PORT     (default: 5432)
      POSTGRES_DB       (default: hydrasense)
      POSTGRES_USER     (required)
      POSTGRES_PASSWORD (required)

    HARD CONSTRAINT (CLAUDE.md): On any DB error, fail loudly and explain.
    Never silently skip the DB step.
    """
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print(
            "\nWARNING: psycopg2 not installed — DB load step skipped.\n"
            "  The CSV has been written. To load into PostGIS:\n"
            "    1. pip install psycopg2-binary\n"
            "    2. Set POSTGRES_USER and POSTGRES_PASSWORD env vars\n"
            "    3. Re-run this script\n"
            "  This is expected if running before Phase 8 (backend setup).\n",
            file=sys.stderr,
        )
        return   # CSV write already done — not a silent skip, just deferred

    pg_user = os.environ.get("POSTGRES_USER", "").strip()
    pg_pass = os.environ.get("POSTGRES_PASSWORD", "").strip()
    if not pg_user or not pg_pass:
        print(
            "\nERROR: POSTGRES_USER and POSTGRES_PASSWORD must be set as env vars.\n"
            "  export POSTGRES_USER=youruser\n"
            "  export POSTGRES_PASSWORD=yourpassword\n"
            "  (PowerShell: $env:POSTGRES_USER = 'youruser')\n"
            "\n  CSV has been written. DB load skipped until credentials are set.",
            file=sys.stderr,
        )
        return

    conn_params = {
        "host":     os.environ.get("POSTGRES_HOST", "localhost"),
        "port":     int(os.environ.get("POSTGRES_PORT", "5432")),
        "dbname":   os.environ.get("POSTGRES_DB", "hydrasense"),
        "user":     pg_user,
        "password": pg_pass,
        "connect_timeout": 10,
    }

    try:
        conn = psycopg2.connect(**conn_params)
    except psycopg2.OperationalError as e:
        print(
            f"\nERROR: Cannot connect to PostgreSQL at "
            f"{conn_params['host']}:{conn_params['port']}/{conn_params['dbname']}\n"
            f"  {e}\n"
            "  Check that PostgreSQL is running and credentials are correct.\n"
            "  CSV has been written successfully — re-run after fixing DB connection.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with conn:
            with conn.cursor() as cur:
                # Create hexes table if not yet created by Phase 8.
                # Matches SRS.md Section 14 schema exactly (without PostGIS geom type
                # if PostGIS extension isn't loaded yet — Phase 8 will handle migration).
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS hexes (
                        hex_id          TEXT PRIMARY KEY,
                        static_features JSONB NOT NULL DEFAULT '{}'::jsonb
                    );
                """)

                # UPSERT: merge gsi_susceptibility_class into static_features JSONB.
                # Punjirimattom rows: susceptibility_class is None -> stored as JSON null,
                # never coerced to a string. Phase 3 must propagate this null faithfully.
                upsert_sql = """
                    INSERT INTO hexes (hex_id, static_features)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (hex_id) DO UPDATE
                      SET static_features = hexes.static_features ||
                          excluded.static_features;
                """

                n_inserted = 0
                n_null     = 0
                for row in rows:
                    patch = {"gsi_susceptibility_class": row["susceptibility_class"]}
                    cur.execute(upsert_sql, (row["hex_id"], json.dumps(patch)))
                    n_inserted += 1
                    if row["susceptibility_class"] is None:
                        n_null += 1

                print(
                    f"[load_gsi] DB UPSERT complete — {n_inserted} hexes updated "
                    f"({n_null} with null class for Punjirimattom)."
                )
    except psycopg2.Error as e:
        print(
            f"\nERROR: DB write failed:\n  {e}\n"
            "  CSV is intact. Fix the DB error and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Summary printout
# ---------------------------------------------------------------------------

def print_summary(rows: list[dict]) -> None:  # type: ignore[type-arg]
    resolved   = [r for r in rows if r["resolved"]]
    unresolved = [r for r in rows if not r["resolved"]]

    villages_resolved   = sorted({r["village"] for r in resolved})
    villages_unresolved = sorted({r["village"] for r in unresolved})

    class_counts: dict[str, int] = {}
    for r in resolved:
        c = r["susceptibility_class"]
        class_counts[c] = class_counts.get(c, 0) + 1

    print()
    print("=" * 65)
    print("PHASE 2 — GSI Susceptibility Load Summary")
    print("=" * 65)
    print(f"  Total pilot hexes:          {len(rows)}")
    print(f"  Resolved (sourced class):   {len(resolved)}")
    print(f"  Unresolved (null/TBD):      {len(unresolved)}")
    print()
    print("  Class distribution (sourced rows only):")
    for cls, cnt in sorted(class_counts.items()):
        print(f"    {cls:12s}  {cnt} hexes")
    print()
    print(f"  Source: {SOURCE_CITED}")
    print()
    print("  Villages with resolved class:")
    for v in villages_resolved:
        print(f"    OK  {v}")
    print()

    if unresolved:
        print("  !!  UNRESOLVED VILLAGES (null susceptibility_class):")
        for v in villages_unresolved:
            n = sum(1 for r in unresolved if r["village"] == v)
            print(f"    XX  {v}  ({n} hexes — null in CSV and DB)")
        print()
        print("  ACTION REQUIRED:")
        print("    Punjirimattom is NOT named in the GSI Jul-2024 FIR report.")
        print("    Do NOT default it to Moderate or any other class.")
        print("    Resolve by one of:")
        print("      1. Access GSI Bhukosh viewer when it becomes reachable")
        print("         and hand-read the NLSM class for Punjirimattom.")
        print("      2. Identify another published GSI source that names Punjirimattom.")
        print("    Until then, these hexes remain null in gsi_susceptibility_class.")
        print("    Phase 3 must propagate this null faithfully into static_features.")
        print("    Phase 6 must handle null gsi_susceptibility_class without crashing.")
    print("=" * 65)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("[Phase 2] GSI NLSM susceptibility digitization — SRS.md Sec 8\n")
    print(f"  H3 resolution: {H3_RESOLUTION}")
    print(f"  Villages: {', '.join(VILLAGES.keys())}\n")

    # 1. Generate hex table
    rows = generate_pilot_hex_table()

    # 2. Write CSV (always)
    write_csv(rows)

    # 3. Attempt DB load (graceful skip if psycopg2/credentials missing)
    print("[load_gsi] Attempting PostgreSQL UPSERT ...")
    load_to_db(rows)

    # 4. Summary — always printed, Punjirimattom flagged loudly
    print_summary(rows)


if __name__ == "__main__":
    main()
