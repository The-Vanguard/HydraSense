"""
fix_provenance.py
-----------------
1. Audits historical_events provenance counts.
2. Back-fills NULL provenance rows as SIMULATED (they are pre-migration seed rows).
3. Prints final state.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "hydrasense.db"

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # --- Audit before ---
    cur.execute("SELECT provenance, COUNT(*) FROM historical_events GROUP BY provenance")
    before = cur.fetchall()
    print("[BEFORE] provenance distribution:")
    for row in before:
        print(f"  {row[0]!r:30s}  {row[1]}")

    null_count = next((c for p, c in before if p is None), 0)
    if null_count == 0:
        print("\n[OK] No NULL provenance rows — Phase 0 gate already satisfied.")
    else:
        print(f"\n[FIX] Back-filling {null_count} NULL rows → SIMULATED")
        cur.execute(
            "UPDATE historical_events SET provenance = 'SIMULATED' WHERE provenance IS NULL"
        )
        conn.commit()
        print(f"[FIX] Updated {cur.rowcount} rows.")

    # --- Audit after ---
    cur.execute("SELECT provenance, COUNT(*) FROM historical_events GROUP BY provenance")
    after = cur.fetchall()
    print("\n[AFTER] provenance distribution:")
    for row in after:
        print(f"  {row[0]!r:30s}  {row[1]}")

    remaining_null = next((c for p, c in after if p is None), 0)
    if remaining_null == 0:
        print("\n[GATE PASS] Phase 0 provenance gate — ALL rows tagged. ✓")
    else:
        print(f"\n[GATE FAIL] Still {remaining_null} NULL rows!")

    conn.close()

if __name__ == "__main__":
    main()
