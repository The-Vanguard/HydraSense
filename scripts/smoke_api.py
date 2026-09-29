"""
scripts/smoke_api.py -- call every endpoint the dashboard uses (plus the newer village / evacuation /
confidence-factor ones) against a running backend and print status, latency and payload size.

  python scripts/smoke_api.py [base_url]        default http://127.0.0.1:8000

Read-only GETs plus one POST to /simulate/risk with a LOW-risk scenario (never Orange/Red, so no push
notification and no alert-state change).
It never approves alerts or triggers scoring.  Exit code 1 if any endpoint returns >= 500.
"""
import json
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
rows, first = [], {}


def call(name, method, path, **kw):
    t = time.time()
    try:
        r = requests.request(method, BASE + path, timeout=kw.pop("timeout", 60), **kw)
        ms = (time.time() - t) * 1000
        try:
            data = r.json()
        except Exception:
            data = None
        rows.append((name, r.status_code, ms, len(r.content), path))
        return r.status_code, data
    except Exception as exc:
        rows.append((name, f"ERR {type(exc).__name__}", (time.time() - t) * 1000, 0, path))
        return None, None


def main():
    call("root", "GET", "/")
    _, regions = call("region list", "GET", "/region/list")
    _, rmap = call("risk map", "GET", "/risk/map")
    hex_id = (rmap[0]["hex_id"] if isinstance(rmap, list) and rmap else None)
    print(f"regions: {len(regions) if isinstance(regions, list) else regions} | risk map hexes: "
          f"{len(rmap) if isinstance(rmap, list) else rmap} | sample hex: {hex_id}")
    if hex_id:
        for nm, p in [("risk hex", f"/risk/{hex_id}"), ("history", f"/risk/{hex_id}/history"),
                      ("uncertainty", f"/risk/{hex_id}/uncertainty"), ("inundation", f"/risk/{hex_id}/inundation"),
                      ("shelters nearest", f"/shelters/nearest/{hex_id}"),
                      ("confidence breakdown", f"/confidence/{hex_id}/breakdown"),
                      ("confidence factors", f"/confidence/{hex_id}/factors"),
                      ("persistent", f"/confidence/{hex_id}/persistent"), ("gate hex", f"/alert/gate/{hex_id}")]:
            call(nm, "GET", p)
    for nm, p in [("alert feed", "/alert/feed"), ("gate pending", "/alert/gate/pending"),
                  ("loeo", "/validation/loeo"), ("loro", "/validation/loro"), ("events map", "/events/map"),
                  ("sim points", "/simulate/points"), ("village drafts", "/village/drafts")]:
        call(nm, "GET", p)
    _, evs = call("events map (data)", "GET", "/events/map")
    if isinstance(evs, list) and evs:
        eid = evs[0].get("event_id")
        call("event rainfall window", "GET", f"/events/{eid}/rainfall-window")
    # A deliberately LOW-risk scenario: /simulate/risk can push an ntfy notification and update the
    # dedup state when a scenario reaches Orange/Red, which a smoke test must never do.
    call("simulate risk (low)", "POST", "/simulate/risk", json={"rainfall_24h": 1.0, "soil_saturation_ratio": 0.2,
                                                                 "slope_deg": 5})
    codes = [r.get("region_code") for r in regions] if isinstance(regions, list) else []
    for code in codes[:2] or []:
        call(f"region hexes {code}", "GET", f"/region/{code}/hexes")
    for code in ("ribhoi-ml", "idukki-kl"):
        s, pr = call(f"village priority {code}", "GET", f"/village/priority?region={code}&limit=5", timeout=180)
        if s == 200 and pr.get("villages"):
            vid = pr["villages"][0]["village_id"]
            first[code] = pr
            call(f"village risk {code}", "GET", f"/village/{vid}/risk?region={code}", timeout=180)
            call(f"evacuation {code}", "GET", f"/evacuation/{vid}?region={code}")
    print(f"\n{'endpoint':30s} {'status':>7s} {'ms':>8s} {'bytes':>9s}")
    bad = 0
    for name, st, ms, size, path in rows:
        flag = "" if st in (200,) else "   <--"
        if not isinstance(st, int) or st >= 500:
            bad += 1
        print(f"{name:30s} {str(st):>7s} {ms:8.0f} {size:9d}{flag}  {path[:60]}")
    for code, pr in first.items():
        v = pr["villages"][0]
        print(f"\n{code}: {pr['count']} villages; top: {v['village_id']} alert_value={v.get('alert_value')} "
              f"quality={v.get('boundary_quality')} hexes_scored={v.get('footprint_hexes_scored')}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
