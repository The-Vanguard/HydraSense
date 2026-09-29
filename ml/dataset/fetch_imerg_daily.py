"""
ml/dataset/fetch_imerg_daily.py -- daily GPM IMERG Final Run rain (V07) for the training table.

For every (0.1 deg cell, UTC day) needed by data/events/training_table_v0p.parquet -- the 15 days
before each row's prediction time -- fetch `precipitation` (mm/day) from NASA GES DISC OPeNDAP
(GPM_3IMERGDF.07, Final Run: gauge-calibrated, ~3.5 month latency).

  * Token: read from the EARTHDATA_TOKEN environment variable ONLY.  It is never written to disk,
    logged or printed.  Without it the script exits.
  * Resumable: results are appended to data/events/imerg_daily_cache.jsonl; cached keys are skipped.
  * 401/403 (auth) stops the whole run at once; 429 / 5xx / timeouts retry with backoff.
  * A missing / fill value is stored as null and stays NaN downstream (never filled).
  * Events before IMERG's start (2000-06) are skipped.
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "data" / "events" / "training_table_v0p.parquet"
CACHE = ROOT / "data" / "events" / "imerg_daily_cache.jsonl"
BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07"
IMERG_START = pd.Timestamp("2000-06-01")
LOOKBACK_DAYS = 16          # window ends at the UTC day of the prediction time; 15 d antecedent + 1
WORKERS = 4
AUTH_FAILS_TO_STOP = 6      # consecutive 401/403 responses (after retries) before the run stops
TIMEOUT = 90

_lock = threading.Lock()
_stop = threading.Event()
_auth_fails = 0                 # consecutive auth failures across workers (a success resets it)


def url_for(day: str) -> str:
    return f"{BASE}/{day[:4]}/{day[4:6]}/3B-DAY.MS.MRG.3IMERG.{day}-S000000-E235959.V07B.nc4"


def needed_keys(df: pd.DataFrame) -> set[tuple[int, int, str]]:
    need = set()
    for r in df.itertuples():
        pt = pd.Timestamp(r.pred_time)
        xi, yi = int((r.lon + 180) / 0.1), int((r.lat + 90) / 0.1)
        end = (pt - timedelta(hours=5.5)).normalize()             # local (IST) -> UTC day
        for k in range(LOOKBACK_DAYS):
            day = end - timedelta(days=k)
            if day >= IMERG_START:
                need.add((xi, yi, day.strftime("%Y%m%d")))
    return need


def fetch_one(key, headers):
    global _auth_fails
    xi, yi, day = key
    q = f".ascii?precipitation[0:0][{xi}:{xi}][{yi}:{yi}]"
    last = None
    for attempt in range(4):
        if _stop.is_set():
            return key, "STOP"
        try:
            r = requests.get(url_for(day) + q, headers=headers, timeout=TIMEOUT)
            if r.status_code in (401, 403):
                # NASA sometimes answers 401 transiently under load (seen mid-run with a valid token):
                # retry with backoff; only a run of consecutive failures stops everything.
                with _lock:
                    _auth_fails += 1
                    if _auth_fails >= AUTH_FAILS_TO_STOP:
                        _stop.set()
                        return key, f"AUTH {r.status_code}"
                last = f"auth {r.status_code}"
                time.sleep(15 * (attempt + 1))
                continue
            with _lock:
                _auth_fails = 0
            if r.status_code == 404:
                return key, None                                  # no file for that day
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            for line in r.text.splitlines():
                if line.startswith("precipitation.precipitation["):
                    v = float(line.rsplit(",", 1)[1])
                    return key, (None if v < -9000 else v)
            return key, None
        except Exception as exc:
            last = exc
            time.sleep(5 * (attempt + 1))
    return key, f"FAIL {last}"


def main():
    token = os.environ.get("EARTHDATA_TOKEN")
    if not token:
        sys.exit("EARTHDATA_TOKEN is not set; nothing fetched.")
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "HydraSense-SIH26192-dataset/1.0"}
    df = pd.read_parquet(TABLE)
    need = needed_keys(df)
    done = set()
    if CACHE.exists():
        for line in CACHE.read_text().splitlines():
            o = json.loads(line)
            done.add(tuple(o["k"].split(",")[:2] + [o["k"].split(",")[2]]))
    todo = [k for k in sorted(need) if (str(k[0]), str(k[1]), k[2]) not in done]
    print(f"needed {len(need)} | cached {len(need) - len(todo)} | to fetch {len(todo)}", flush=True)
    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex, open(CACHE, "a") as f:
        futs = [ex.submit(fetch_one, k, headers) for k in todo]
        for n, fu in enumerate(as_completed(futs), 1):
            key, val = fu.result()
            if isinstance(val, str):
                if val.startswith("AUTH"):
                    print(f"STOP: {val} -- NASA rejected the token; nothing more will be requested", flush=True)
                if val != "STOP":
                    fail += 1
                continue
            with _lock:
                f.write(json.dumps({"k": f"{key[0]},{key[1]},{key[2]}", "v": val}) + "\n")
                f.flush()
            ok += 1
            if n % 250 == 0:
                print(f"  {n}/{len(todo)}  ok={ok} fail={fail}  {time.time() - t0:.0f}s", flush=True)
    print(f"finished: ok={ok} failed={fail} of {len(todo)} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
