"""scripts/inspect_schema.py — print historical_events schema and sample NULL rows."""
import sqlite3, json
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "hydrasense.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=" * 60)
print("TABLE: historical_events — PRAGMA table_info")
print("=" * 60)
cols = conn.execute("PRAGMA table_info(historical_events)").fetchall()
for c in cols:
    print(f"  cid={c['cid']:2d}  name={c['name']:<30s}  type={c['type']:<50s}  notnull={c['notnull']}  dflt={c['dflt_value']}  pk={c['pk']}")

print()
print("=" * 60)
print("PROVENANCE BREAKDOWN")
print("=" * 60)
for row in conn.execute("SELECT provenance, COUNT(*) as n FROM historical_events GROUP BY provenance"):
    print(f"  provenance={row['provenance']}  count={row['n']}")

print()
print("=" * 60)
print("SAMPLE — 5 NULL provenance rows (all columns)")
print("=" * 60)
null_rows = conn.execute("SELECT * FROM historical_events WHERE provenance IS NULL LIMIT 5").fetchall()
col_names = [c['name'] for c in cols]
for r in null_rows:
    d = {k: r[k] for k in col_names}
    print(json.dumps(d, indent=2, default=str))
    print()

print("=" * 60)
print("SAMPLE — 2 SIMULATED rows (for comparison)")
print("=" * 60)
sim_rows = conn.execute("SELECT * FROM historical_events WHERE provenance = 'SIMULATED' LIMIT 2").fetchall()
for r in sim_rows:
    d = {k: r[k] for k in col_names}
    print(json.dumps(d, indent=2, default=str))
    print()

conn.close()
