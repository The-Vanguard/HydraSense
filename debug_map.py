import sys
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from backend.database import init_db
from backend.seed import run_seed
init_db()
run_seed()

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app, raise_server_exceptions=True)

try:
    r = client.get("/risk/map")
    print(f"Status: {r.status_code}")
    print(r.text[:500])
except Exception as e:
    import traceback
    traceback.print_exc()

