"""Look up Wikipedia article coordinates for candidate place names (structured API, no scraping).
Prints candidates only; nothing is written to the override file until reviewed."""
import sys, math, requests, pandas as pd
API="https://en.wikipedia.org/w/api.php"; H={"User-Agent":"HydraSense-SIH26192-event-geocoder/1.0"}
def look(q, n=4):
    r=requests.get(API,params={"action":"query","format":"json","generator":"search","gsrsearch":q,"gsrlimit":n,
        "prop":"coordinates|description","colimit":n,"coprimary":"primary"},headers=H,timeout=20).json()
    out=[]
    for p in (r.get("query",{}).get("pages",{}) or {}).values():
        c=(p.get("coordinates") or [None])[0]
        if c: out.append((p["title"],c["lat"],c["lon"],p.get("description","")))
    return out
def hav(a,b,c,d):
    R=6371; p=math.radians; x=math.sin(p(c-a)/2)**2+math.cos(p(a))*math.cos(p(c))*math.sin(p(d-b)/2)**2
    return 2*R*math.asin(math.sqrt(x))
if __name__=="__main__":
    g=pd.read_csv("data/events/historical_events_geocoded.csv").set_index("event_id")
    for line in sys.stdin:
        ev,q=[x.strip() for x in line.split("|",1)]
        base=(g.loc[ev,"lat"],g.loc[ev,"lon"]); print(f"\n## {ev}  osm=({base[0]:.3f},{base[1]:.3f})  q={q}")
        for t,la,lo,d in look(q):
            print(f"   {t[:45]:45s} {la:8.4f} {lo:8.4f}  d_osm={hav(base[0],base[1],la,lo):6.1f} km  {d[:40]}")
