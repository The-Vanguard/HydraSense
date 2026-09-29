"""
backend/onboarding/stream_links.py -- stream-link micro-catchments from a D8 flow-direction grid.

Pure numpy (no numba, no pysheds), so it is testable and immune to the numba / numpy version
breakage that stops pysheds' own `catchment()` (native crash) and `fill_depressions()` here.

Method (standard "stream link" sub-catchments):
  1. stream cells      : accumulation >= threshold (cells)
  2. junction cells    : stream cells with >= 2 stream cells draining into them
  3. link outlets      : stream cells whose downstream cell is a junction, that leave the stream
                         network, or that drain off the grid  -> one micro-catchment per outlet
  4. labelling         : every cell takes the label of the first outlet on its downstream path
                         (incremental, non-overlapping catchments); cells that never reach an outlet
                         stay 0
  5. attributes        : cell count, longest flow path to the outlet (m), relief (m), mean slope,
                         channel slope, Kirpich time of concentration  (v2 Sec. 7.3 inputs)

Flow-direction codes follow pysheds' default dirmap (N, NE, E, SE, S, SW, W, NW).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

DIRMAP_DEFAULT = (64, 128, 1, 2, 4, 8, 16, 32)
OFFSETS = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1))


def downstream_index(fdir: np.ndarray, dirmap: Sequence[int] = DIRMAP_DEFAULT) -> np.ndarray:
    """Flat index of each cell's downstream neighbour, or -1 (no flow, nodata, or off the grid)."""
    h, w = fdir.shape
    rr, cc = np.indices((h, w))
    dn = np.full((h, w), -1, dtype=np.int64)
    for code, (dr, dc) in zip(dirmap, OFFSETS):
        m = fdir == code
        r2, c2 = rr + dr, cc + dc
        ok = m & (r2 >= 0) & (r2 < h) & (c2 >= 0) & (c2 < w)
        dn[ok] = (r2 * w + c2)[ok]
    return dn.ravel()


def kirpich_tc_min(length_m: float, slope_m_m: float) -> float:
    """Kirpich time of concentration in minutes: 0.0195 * L^0.77 * S^-0.385 (L in m, S in m/m)."""
    if length_m <= 0:
        return 0.0
    return 0.0195 * (length_m ** 0.77) * (max(slope_m_m, 1e-3) ** -0.385)


def stream_link_catchments(
    fdir: np.ndarray,
    acc: np.ndarray,
    dem: np.ndarray,
    dx_m: float,
    dy_m: float,
    threshold_cells: int,
    dirmap: Sequence[int] = DIRMAP_DEFAULT,
) -> dict:
    """
    Returns dict with:
      labels  (h, w) int32, 0 = not in any micro-catchment
      ids     array of catchment ids (1..K)
      outlet_rc  (K, 2) row/col of each outlet
      cells, flow_length_m, relief_m, mean_slope_deg, channel_slope_m_m, tc_min   (arrays, len K)
    """
    h, w = fdir.shape
    n = h * w
    dn = downstream_index(fdir, dirmap)
    acc_f = np.asarray(acc, dtype=np.float64).ravel()
    z = np.asarray(dem, dtype=np.float64).ravel()
    stream = acc_f >= threshold_cells
    has_dn = dn >= 0
    safe_dn = np.where(has_dn, dn, 0)

    # 1-2. stream inflow counts and junctions
    src = np.nonzero(stream & has_dn)[0]
    tgt = dn[src]
    into_stream = stream[tgt]
    inflow = np.bincount(tgt[into_stream], minlength=n)
    junction = stream & (inflow >= 2)

    # 3. link outlets
    is_end = stream & (~has_dn | junction[safe_dn] | ~stream[safe_dn])
    end_idx = np.nonzero(is_end)[0]
    k = len(end_idx)
    if k == 0:
        return dict(labels=np.zeros((h, w), np.int32), ids=np.array([], int), outlet_rc=np.zeros((0, 2), int),
                    cells=np.array([], int), flow_length_m=np.array([]), relief_m=np.array([]),
                    mean_slope_deg=np.array([]), channel_slope_m_m=np.array([]), tc_min=np.array([]))
    ids = np.arange(1, k + 1, dtype=np.int32)
    lab = np.zeros(n, dtype=np.int32)
    lab[end_idx] = ids

    # 4. downstream-first labelling and flow-path length
    order = np.argsort(-acc_f, kind="stable")           # downstream cells have larger accumulation
    rr, cc = np.divmod(np.arange(n), w)
    dr = np.where(has_dn, (safe_dn // w) - rr, 0)
    dc = np.where(has_dn, (safe_dn % w) - cc, 0)
    step = np.hypot(dr * dy_m, dc * dx_m)
    lab_l, dn_l, step_l = lab.tolist(), dn.tolist(), step.tolist()
    dist_l = [0.0] * n
    end_l = is_end.tolist()
    for i in order.tolist():
        if end_l[i] or lab_l[i]:
            continue
        d = dn_l[i]
        if d >= 0:
            li = lab_l[d]
            if li:
                lab_l[i] = li
                dist_l[i] = dist_l[d] + step_l[i]
    lab = np.array(lab_l, dtype=np.int32)
    dist = np.array(dist_l)

    # 5. attributes per catchment
    valid = lab > 0
    L = lab[valid]
    cells = np.bincount(L, minlength=k + 1)[1:]
    flow_len = np.zeros(k + 1)
    np.maximum.at(flow_len, L, dist[valid])
    zmax = np.full(k + 1, -np.inf)
    np.maximum.at(zmax, L, z[valid])
    z_out = z[end_idx]
    relief = np.maximum(zmax[1:] - z_out, 0.0)
    zg = np.asarray(dem, dtype=np.float64)
    gy, gx = np.gradient(zg, dy_m, dx_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).ravel()
    mean_slope = np.bincount(L, weights=slope[valid], minlength=k + 1)[1:] / np.maximum(cells, 1)
    flow_len = flow_len[1:]
    chan_slope = np.where(flow_len > 0, relief / np.maximum(flow_len, 1e-9), 0.0)
    tc = np.array([kirpich_tc_min(fl, s) for fl, s in zip(flow_len, chan_slope)])
    outlet_rc = np.column_stack(np.divmod(end_idx, w))
    return dict(labels=lab.reshape(h, w), ids=ids, outlet_rc=outlet_rc, cells=cells,
                flow_length_m=flow_len, relief_m=relief, mean_slope_deg=mean_slope,
                channel_slope_m_m=chan_slope, tc_min=tc)
