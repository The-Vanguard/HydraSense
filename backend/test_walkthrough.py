import sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')

from backend.database import init_db; init_db()
from backend.seed import run_seed; run_seed()
from fastapi.testclient import TestClient
from backend.main import app
import h3
from datetime import datetime, timezone, timedelta
from pathlib import Path

client     = TestClient(app, raise_server_exceptions=True)
PILOT_HEX  = h3.latlng_to_cell(11.5185, 76.0524, 8)
STATE_PATH = Path('data/iot/sensor_state.json')
checks = []

def chk(label, cond, detail=''):
    sym = '[OK]' if cond else '[FAIL]'
    print(f'  {sym} {label}' + (f' -- {detail}' if detail else ''))
    checks.append((label, cond))
    return cond

print('\n' + '='*65)
print('LIVE WALKTHROUGH: Simulator -> Phase 8 -> Dropout -> Label')
print('='*65)

print('\n[1] GET /validation/loeo -- corrected numbers (1440 min, no FPR)')
r = client.get('/validation/loeo')
chk('endpoint 2xx', r.status_code == 200, str(r.status_code))
if r.status_code == 200:
    body   = r.json()
    loeo   = body.get('summary', body)  # endpoint nests under 'summary'
    det    = loeo.get('detection_rate')
    timing = loeo.get('timing_error', {})
    fpr    = loeo.get('false_positive_rate')
    median = timing.get('median_min')
    chk('detection_rate=1.0', det == 1.0, str(det))
    chk('median_lead=1440 not old 2880', median == 1440.0, str(median))
    chk('FPR is null', fpr is None, str(fpr))
    chk('N=30 events', loeo.get('loeo_n_events') == 30)
    print(f'     detection_rate={det}, median={median} min, fpr={fpr}')

print('\n[2] POST /ingest/iot -- sensor ACTIVE')
now_ts = datetime.now(timezone.utc).isoformat()
r = client.post('/ingest/iot', json={'device_id':'SIM_DEV_001','hex_id':PILOT_HEX,'timestamp':now_ts,'sensor_type':'rainfall','value':22.4,'battery':3.6})
chk('POST -> 202', r.status_code == 202, str(r.status_code))
state = json.loads(STATE_PATH.read_text())
hs = state.get(PILOT_HEX, {})
chk('sensor_state.json written', PILOT_HEX in state)
chk('anomaly_flag=False', hs.get('anomaly_flag') == False)
last_seen_val = str(hs.get('last_seen_utc', ''))[:19]
print(f'     last_seen={last_seen_val}, anomaly_flag={hs.get("anomaly_flag")}')

print('\n[3] GET /risk/{hex} -- normal state')
r = client.get(f'/risk/{PILOT_HEX}')
chk('200 OK', r.status_code == 200)
risk_n = r.json() if r.status_code == 200 else {}
chk('data_source=live', risk_n.get('data_source') == 'live')
chk('risk_score float', isinstance(risk_n.get('risk_score'), float))
print(f'     score={risk_n.get("risk_score", 0):.1f}, tier={risk_n.get("tier")}, src={risk_n.get("data_source")}')

print('\n[4] Phase 10 DROPOUT (anomaly_flag=True)')
old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
state[PILOT_HEX]['last_seen_utc'] = old_ts
state[PILOT_HEX]['anomaly_flag']  = True
STATE_PATH.write_text(json.dumps(state, indent=2))
chk('dropout written', json.loads(STATE_PATH.read_text()).get(PILOT_HEX,{}).get('anomaly_flag') == True)
print(f'     anomaly_flag=True, last_seen={old_ts[:19]}')

print('\n[5] _compute_iot_anomaly_flag reads dropout')
from ml.features.dynamic_features import _compute_iot_anomaly_flag
flag = _compute_iot_anomaly_flag(PILOT_HEX)
chk('flag=True during dropout', flag == True, str(flag))

print('\n[6] GET /risk during dropout')
r = client.get(f'/risk/{PILOT_HEX}')
chk('200 OK', r.status_code == 200)
risk_d = r.json() if r.status_code == 200 else {}
chk('data_source present', 'data_source' in risk_d)
chk('risk_score float', isinstance(risk_d.get('risk_score'), float))
print(f'     score={risk_d.get("risk_score", 0):.1f}, tier={risk_d.get("tier")}')
print('     NOTE: external-data-only label = Phase 12 UI; API signals via feature vector')

print('\n[7] Sensor restore')
state[PILOT_HEX]['last_seen_utc'] = datetime.now(timezone.utc).isoformat()
state[PILOT_HEX]['anomaly_flag']  = False
STATE_PATH.write_text(json.dumps(state, indent=2))
chk('flag=False after restore', _compute_iot_anomaly_flag(PILOT_HEX) == False)

print('\n[8] Supporting endpoints')
for path, label in [('/','health (GET /)'),('/risk/map','risk/map'),
    (f'/risk/{PILOT_HEX}/history','risk/history'),
    (f'/risk/{PILOT_HEX}/uncertainty','uncertainty'),
    (f'/shelters/nearest/{PILOT_HEX}','shelters/nearest')]:
    r = client.get(path)
    chk(f'GET /{label} 200', r.status_code == 200, str(r.status_code))

passed = sum(1 for _,c in checks if c)
total  = len(checks)
print(f'\n{"="*65}')
print(f'  {passed}/{total} checks passed')
print('  LIVE WALKTHROUGH PASSED -- demo-ready' if passed==total else f'  FAILED: {[l for l,c in checks if not c]}')
print('='*65)
sys.exit(0 if passed==total else 1)
