"""tests/test_stream_links.py -- stream-link micro-catchments on a hand-built Y-shaped drainage.

Layout (30 rows x 20 cols, cell = 30 m):
  rows 0-14 : cols < 10 drain to a west valley at col 5, cols >= 10 to an east valley at col 15
  row 14    : the two valleys step diagonally into row 15
  row 15    : every cell drains along the row toward col 10 (west from the east, east from the west)
  rows 16-29: cells drain toward col 10, then south down col 10 to the outlet (29, 10)
Junction = (15, 10) with inflow from (15, 9) and (15, 11)  ->  exactly 3 micro-catchments.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.onboarding import stream_links as sl  # noqa: E402

N, E, S, W, NE, SE, SW, NW = 64, 1 * 0 + 1, 4, 16, 128, 2, 8, 32   # pysheds dirmap: E=1, SE=2, S=4, SW=8, W=16
E = 1
H, WD, CELL = 30, 20, 30.0


def build_fdir():
    f = np.zeros((H, WD), dtype=np.int32)
    for r in range(H):
        for c in range(WD):
            if r < 14:
                target = 5 if c < 10 else 15
                f[r, c] = S if c == target else (E if c < target else W)
            elif r == 14:
                if c == 5:
                    f[r, c] = SE
                elif c == 15:
                    f[r, c] = SW
                else:
                    target = 5 if c < 10 else 15
                    f[r, c] = E if c < target else W
            elif r == 15:
                f[r, c] = S if c == 10 else (E if c < 10 else W)
            else:
                f[r, c] = S if c == 10 else (E if c < 10 else W)
    return f


def accumulation(fdir):
    dn = sl.downstream_index(fdir)
    # elevation = -(steps to outlet) so downstream is always lower; process upstream first
    depth = np.full(dn.size, -1)

    def steps(i):
        chain = []
        while i >= 0 and depth[i] < 0:
            chain.append(i)
            i = dn[i]
        base = depth[i] if i >= 0 else 0
        for k, j in enumerate(reversed(chain)):
            depth[j] = base + k + 1
    for i in range(dn.size):
        steps(i)
    acc = np.ones(dn.size)
    for i in np.argsort(-depth, kind="stable"):
        if dn[i] >= 0:
            acc[dn[i]] += acc[i]
    return acc.reshape(fdir.shape), depth.reshape(fdir.shape).astype(float)


@pytest.fixture(scope="module")
def result():
    fdir = build_fdir()
    acc, depth = accumulation(fdir)
    dem = 1000.0 + depth * 3.0                     # downstream lower; 3 m per step
    return sl.stream_link_catchments(fdir, acc, dem, CELL, CELL, threshold_cells=12), fdir


def test_downstream_index_off_grid_is_minus_one():
    f = np.array([[4, 4], [4, 4]], dtype=np.int32)              # everything flows south
    dn = sl.downstream_index(f)
    assert dn.tolist() == [2, 3, -1, -1]                        # bottom row drains off the grid
    assert sl.downstream_index(np.zeros((2, 2), np.int32)).tolist() == [-1] * 4     # no flow


def test_three_micro_catchments_at_one_junction(result):
    res, _ = result
    assert len(res["ids"]) == 3
    assert sorted(map(tuple, res["outlet_rc"].tolist())) == [(15, 9), (15, 11), (29, 10)]


def test_partition_covers_every_cell_once(result):
    res, _ = result
    labels = res["labels"]
    assert (labels > 0).all() and res["cells"].sum() == H * WD
    assert set(np.unique(labels)) == {1, 2, 3}


def test_headwater_cells_belong_to_the_right_tributary(result):
    res, _ = result
    lab = res["labels"]
    west, east, main = lab[0, 3], lab[0, 17], lab[20, 10]
    assert len({west, east, main}) == 3
    assert lab[14, 5] == west and lab[14, 15] == east and lab[15, 9] == west and lab[15, 11] == east
    assert lab[15, 10] == main and lab[29, 10] == main             # junction cell starts the main stem
    assert lab[16, 0] == main and lab[16, 19] == main


def test_longest_flow_path_and_slopes(result):
    res, _ = result
    main = int(result[0]["labels"][20, 10])
    k = list(res["ids"]).index(main)
    # longest path in the main catchment: (16,0) -> 10 cells east -> 13 cells south = 23 cells
    assert res["flow_length_m"][k] == pytest.approx(23 * CELL)
    assert (res["flow_length_m"] > 0).all() and (res["relief_m"] > 0).all()
    assert (res["channel_slope_m_m"] > 0).all() and (res["tc_min"] > 0).all()


def test_kirpich_matches_the_formula():
    assert sl.kirpich_tc_min(1000.0, 0.05) == pytest.approx(0.0195 * 1000 ** 0.77 * 0.05 ** -0.385)
    assert sl.kirpich_tc_min(0.0, 0.1) == 0.0
    assert sl.kirpich_tc_min(500.0, 0.0) > 0                        # slope floor, no divide-by-zero


def test_no_stream_cells_gives_empty_result():
    fdir = build_fdir()
    acc, depth = accumulation(fdir)
    res = sl.stream_link_catchments(fdir, acc, 1000 + depth, CELL, CELL, threshold_cells=10_000)
    assert len(res["ids"]) == 0 and (res["labels"] == 0).all()
