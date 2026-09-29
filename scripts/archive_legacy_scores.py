"""
scripts/archive_legacy_scores.py -- move the degenerate model's constant scores out of `risk_scores`.

The old fusion model (ml/models/fusion_model.pkl) returned one constant for every hex without terrain
features -- (risk 58.2311, confidence 28.7771, Orange) and two near-identical variants -- so those rows
say nothing about any hex, yet they show up as "current" scores on the map and in the village table.

This script COPIES exactly those rows into `risk_scores_archive_legacy_model` and then deletes them from
`risk_scores`.  Nothing else is touched.  A backup copy of the database file is made first.  Re-running is
safe (rows already archived are not matched again).  `--dry-run` only counts.

  python scripts/archive_legacy_scores.py [--dry-run]
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "hydrasense.db"
# (risk_score, confidence_score) signatures of the degenerate constant outputs (rounded to 4 dp)
SIGNATURES = [(58.2311, 28.7771), (58.2322, 28.8691), (52.9883, 25.5932)]


def main(dry: bool):
    conn = sqlite3.connect(DB)
    where = " OR ".join("(ROUND(risk_score,4)=? AND ROUND(confidence_score,4)=?)" for _ in SIGNATURES)
    params = [v for sig in SIGNATURES for v in sig]
    n = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT hex_id) FROM risk_scores WHERE {where}", params).fetchone()
    total = conn.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
    print(f"matching legacy-constant rows: {n[0]} across {n[1]} hexes (of {total} rows in risk_scores)")
    if dry or n[0] == 0:
        return
    backup = DB.with_name(f"hydrasense.backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    shutil.copy2(DB, backup)
    print("backup:", backup.name)
    conn.execute("CREATE TABLE IF NOT EXISTS risk_scores_archive_legacy_model AS SELECT * FROM risk_scores WHERE 0")
    conn.execute(f"INSERT INTO risk_scores_archive_legacy_model SELECT * FROM risk_scores WHERE {where}", params)
    conn.execute(f"DELETE FROM risk_scores WHERE {where}", params)
    conn.commit()
    print("archived:", conn.execute("SELECT COUNT(*) FROM risk_scores_archive_legacy_model").fetchone()[0],
          "| left in risk_scores:", conn.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0])


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
