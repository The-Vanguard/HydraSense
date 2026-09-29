"""tests/test_onboarding_fixes.py -- regression tests for onboarding fixes (no network)."""
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import h3
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("shapely")
from backend.onboarding import pipeline, villages  # noqa: E402

BBOX = {"south": 25.70, "north": 26.00, "west": 91.80, "east": 92.10}


def test_onboarding_root_is_the_repo_not_its_parent():
    # parents[3] used to point one folder above the repo and wrote data outside it
    from backend.onboarding import dem, geopackage, soilgrids
    for mod_root in (dem.ROOT, geopackage.ROOT, soilgrids.ROOT, pipeline.ROOT, villages.ROOT):
        assert (mod_root / "backend" / "onboarding").is_dir()


def test_voronoi_villages_one_cell_per_node_capped_and_labelled():
    nodes = [{"id": i, "lat": 25.75 + 0.06 * i, "lon": 91.85 + 0.05 * i, "name": f"V{i}", "population": None}
             for i in range(4)]
    warns = []
    out = villages._voronoi_villages(nodes, BBOX, warns)
    assert len(out) == 4 and not warns
    from shapely.geometry import Point
    for feat, n in zip(sorted(out, key=lambda f: f["name"]), nodes):
        assert feat["boundary_quality"] == "voronoi_approx"
        assert feat["geometry"].contains(Point(n["lon"], n["lat"]))
        assert feat["geometry"].area <= 3.1416 * villages.VORONOI_MAX_RADIUS_DEG ** 2 + 1e-9


def test_voronoi_needs_at_least_two_nodes():
    assert villages._voronoi_villages([], BBOX, []) == []
    assert villages._voronoi_villages([{"id": 1, "lat": 25.8, "lon": 91.9, "name": "A", "population": None}],
                                      BBOX, []) == []


def _hex_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE hexes (hex_id TEXT PRIMARY KEY, geom TEXT, static_features TEXT DEFAULT '{}',"
                 " region_code TEXT, resolution INTEGER)")
    conn.commit()
    conn.close()


def test_db_seed_uses_real_hexes_schema_and_is_idempotent(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    db = tmp_path / "data" / "hydrasense.db"
    _hex_db(db)
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(25.85, 91.95, 8), 1))
    grid = SimpleNamespace(hex_ids=cells, resolution=8,
                           hex_features={c: {"slope_deg": 12.0, "has_local_calibration": True} for c in cells})
    soil = SimpleNamespace(c_prime_kpa=25.0, phi_deg=32.0, z_m=1.5, gamma_kn_m3=14.0, data_source="soilgrids_wcs")
    cal = SimpleNamespace()
    pipeline._seed_db_hexes("demo-ml", grid, soil, cal)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT hex_id, geom, static_features, region_code, resolution FROM hexes").fetchall()
    assert len(rows) == len(cells) == 7
    geom = json.loads(rows[0][1])
    assert geom["type"] == "Polygon" and geom["coordinates"][0][0] == geom["coordinates"][0][-1]
    assert json.loads(rows[0][2])["soil_data_source"] == "soilgrids_wcs"
    assert {r[3] for r in rows} == {"demo-ml"} and {r[4] for r in rows} == {8}
    pipeline._seed_db_hexes("demo-ml", grid, soil, cal)             # rerun updates, never duplicates
    assert conn.execute("SELECT COUNT(*) FROM hexes").fetchone()[0] == 7
