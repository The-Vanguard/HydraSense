"""
backend/coarse_cache.py -- share one live weather fetch across all hexes in the same coarse cell.

Open-Meteo's rainfall / soil-moisture / forecast fields are ~10 km products, so 1,300 hexes in a
district need ~60 fetches, not 1,300 (v2 Sec. 14.6: "per-hex calls to a dynamic API are grouped by a
coarse spatial key").  The first hex to ask in a cell supplies the sample point for that cell.

  * only SUCCESSFUL live results are cached (`success(result)`); a failure or a cached-file fallback is
    never stored, so the next request retries the live source and the data label stays truthful
  * entries expire after ttl_s (default 10 min, well inside the 15-min scoring cycle)
  * single-flight: when several scoring threads ask for the same cell at once, only the first one calls the
    API and the others wait for its result (parallel duplicate calls were tripping Open-Meteo's rate limit)
"""
from __future__ import annotations

import functools
import threading
import time
from typing import Callable


def coarse_cached(ttl_s: float = 600.0, cell_deg: float = 0.1, success: Callable = lambda r: True,
                  max_entries: int = 4000):
    def deco(fn):
        store: dict = {}
        lock = threading.Lock()
        key_locks: dict = {}                      # one lock per cell: single-flight fetches

        @functools.wraps(fn)
        def wrapper(lat, lon, *args, **kwargs):
            key = (round(lat / cell_deg), round(lon / cell_deg), args, tuple(sorted(kwargs.items())))
            with lock:
                hit = store.get(key)
                if hit and time.time() - hit[0] < ttl_s:
                    return hit[1]
                klock = key_locks.setdefault(key, threading.Lock())
            with klock:                             # others for this cell wait here for the first fetch
                with lock:
                    hit = store.get(key)
                    if hit and time.time() - hit[0] < ttl_s:
                        return hit[1]
                result = fn(lat, lon, *args, **kwargs)
                if success(result):
                    with lock:
                        if len(store) >= max_entries:
                            store.clear()
                            key_locks.clear()
                        store[key] = (time.time(), result)
                return result

        wrapper.cache_clear = store.clear
        wrapper.cache_size = lambda: len(store)
        return wrapper
    return deco
