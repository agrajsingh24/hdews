"""Independent reproduction of claimed defects. Run with: python verify_claims.py <repo_root>
Works against both the baseline commit and the fixed tree (only uses APIs present in both)."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT / "backend"))
os.environ["HDEWS_DEMO_PASSWORD"] = "pw-test"
os.environ["FIELD_GATEWAY_INGEST_KEY"] = "key-test"
os.environ.pop("HDEWS_ENV", None)

from starlette.testclient import TestClient  # noqa: E402
from app import clock  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed import seed  # noqa: E402
from app.services import audit  # noqa: E402
from app.services.risk_engine import assess, build_features, merge_config  # noqa: E402

out = []
def rec(bug, msg): out.append(f"{bug:10} {msg}"); print(out[-1], flush=True)

def fresh_client(**kw):
    db = Database("sqlite:///:memory:"); seed(db, quiet=True)
    s = load_settings(database_url="sqlite:///:memory:", enable_background_reassessment=False, app_env="test",
                      llm_provider="none", llm_api_key="", **kw)
    return db, TestClient(create_app(s, db), raise_server_exceptions=False)

def login(c, u):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": u, "password": "pw-test"}).json()["token"]}

KEY = {"X-HDEWS-Ingest-Key": "key-test", "content-type": "application/json"}

# HDEWS-001: Infinity reading
db, c = fresh_client(); v = login(c, "viewer")
now = c.get("/api/health").json()["time"]
r = c.post("/api/ingestion/FIELD-GATEWAY-01", content=json.dumps({"readings": [{"sensor_id": "AGM-03-SOIL", "observed_at": now, "value": float("inf")}]}), headers=KEY)
rec("HDEWS-001", f"ingest Infinity -> {r.status_code}; GET /overview -> {c.get('/api/overview', headers=v).status_code}")

# HDEWS-002: unit mismatch
r = c.post("/api/ingestion/FIELD-GATEWAY-01", json={"readings": [{"sensor_id": "AGM-03-RIVER", "observed_at": now, "value": 9.8, "unit": "ft", "idempotency_key": "u1"}]}, headers=KEY)
rec("HDEWS-002", f"value with unit 'ft' for a metres sensor -> {r.status_code} accepted={r.json().get('accepted')}")

# HDEWS-003: double counting same-timestamp readings from another origin
db, c = fresh_client(); a = login(c, "analyst")
c.post("/api/demo/scenario", headers=a, json={"site_ids": ["SNP-05"], "preset": "increasing_rainfall"})
def rain1h():
    r = c.post("/api/sites/SNP-05/assess", headers=a).json()["assessments"][0]
    return next(f["value"] for f in r["factors"] if f["key"] == "rain_1h_mm")
before = rain1h()
with db.tx() as tx:
    ref = clock.now()
    rows = tx.all("SELECT * FROM observations WHERE sensor_id='SNP-05-RAIN' AND observed_at > ? ORDER BY observed_at", (clock.iso(ref - timedelta(hours=1)),))
readings = [{"sensor_id": "SNP-05-RAIN", "observed_at": o["observed_at"], "value": o["value"], "idempotency_key": f"d{o['id']}"} for o in rows]
c.post("/api/ingestion/FIELD-GATEWAY-01", json={"readings": readings}, headers=KEY)
rec("HDEWS-003", f"rain_1h before={before} after re-sending the same readings as OBSERVED={rain1h()}")

# HDEWS-008 / 009 / 010 / 011 directly on the engine
REF = clock.parse("2026-07-15T12:00:00Z")
SENS = [{"id": t, "sensor_type": t, "label": t, "expected_interval_s": 900, "status": "active"} for t in ("rain_gauge", "soil_moisture", "extensometer")]
_i = iter(range(1, 10**6))
def ser(fn, hours=26, end_off_min=0, q="good"):
    o, end = [], REF - timedelta(minutes=end_off_min); t = end - timedelta(hours=hours)
    while t <= end:
        o.append({"id": next(_i), "value": fn((REF - t).total_seconds() / 3600), "observed_at": clock.iso(t), "received_at": clock.iso(t), "quality_status": q, "origin": "SIMULATED"})
        t += timedelta(minutes=15)
    return o
def run(obs):
    cfg = merge_config(None); f = build_features(SENS, obs, cfg, REF)
    return assess({"id": "S", "name": "S"}, "landslide", f["indicators"], f["health"], cfg, REF), f
base = {"rain_gauge": ser(lambda h: 0.0), "soil_moisture": ser(lambda h: 25.0), "extensometer": ser(lambda h: 20 - h * 0.3)}
r, _ = run(base)
off = dict(base, extensometer=ser(lambda h: 20 - h * 0.3, hours=30, end_off_min=7 * 60))
r2, _ = run(off)
rec("HDEWS-009", f"displacement 7mm/24h: {r['risk_tier']}/{r['reliability']} -> extensometer offline 7h: {r2['risk_tier']}/{r2['reliability']}")
soil8 = ser(lambda h: 45.0, hours=30, end_off_min=5 * 60) + [dict(o, quality_status="bad") for o in ser(lambda h: 99.0, hours=4)]
r3, f3 = run(dict(base, soil_moisture=soil8, extensometer=ser(lambda h: 20.0)))
soil = next(x for x in r3["factors"] if x["key"] == "soil_moisture_pct")
rec("HDEWS-008", f"good soil 5h old + 4h of bad readings: soil status={soil['status']} as_of={soil['as_of']} sensor state={f3['health']['soil_moisture'].state}")
r4, _ = run(dict(base, soil_moisture=ser(lambda h: float("nan")), extensometer=ser(lambda h: 20.0)))
soil = next(x for x in r4["factors"] if x["key"] == "soil_moisture_pct")
rec("HDEWS-010", f"NaN soil readings -> soil level={soil['level']} status={soil['status']}; tier {r4['risk_tier']}/{r4['reliability']}")

# HDEWS-006: threshold editor
db, c = fresh_client(); adm = login(c, "admin")
r1 = c.put("/api/sites/AGM-03/config", headers=adm, json={"overrides": {"landslide": {"rain_24hr_mm": {"watch": 1, "high": 2}}}})
r2 = c.put("/api/sites/AGM-03/config", headers=adm, json={"overrides": {"landslide": {"rain_24h_mm": {"watch": True, "high": 2}}}})
r3 = c.put("/api/sites/AGM-03/config", headers=adm, content='{"overrides": {"landslide": {"soil_moisture_baseline_pct": 1e999}}}', headers2=None) if False else c.put("/api/sites/AGM-03/config", headers={**adm, "content-type": "application/json"}, content='{"overrides": {"landslide": {"soil_moisture_baseline_pct": 1e999}}}')
rec("HDEWS-006", f"misspelt key -> {r1.status_code}; boolean threshold -> {r2.status_code}; 1e999 -> {r3.status_code}")

# HDEWS-018: delete newest audit event
with db.tx() as tx:
    tx.execute("DROP TRIGGER audit_log_no_delete")
    n = tx.scalar("SELECT COUNT(*) FROM audit_log")
    tx.execute("DELETE FROM audit_log WHERE seq = (SELECT MAX(seq) FROM audit_log)")
    rec("HDEWS-018", f"after deleting newest of {n} audit events: verify -> {audit.verify_chain(tx)}")

# HDEWS-023: wrong method
rec("HDEWS-023", f"DELETE /api/alerts -> {c.delete('/api/alerts', headers=adm).status_code}")

# HDEWS-020: LIKE wildcard
rec("HDEWS-020", f"incident search q='%' -> total {c.get('/api/incidents?q=%25', headers=adm).json()['total']} (9 records, none contain '%')")

# HDEWS-012: production seed
with tempfile.TemporaryDirectory() as d:
    env = dict(os.environ, HDEWS_ENV="production", DATABASE_URL=f"sqlite:///{d}/p.db"); env.pop("HDEWS_DEMO_PASSWORD")
    p = subprocess.run([sys.executable, str(ROOT / "scripts/seed_demo_data.py")], env=env, capture_output=True, text=True, cwd=d)
    rec("HDEWS-012", f"seed with HDEWS_ENV=production -> rc={p.returncode} out={(p.stdout + p.stderr).strip().splitlines()[0][:90]!r}")

# HDEWS-013: reset_db deletes non-HDEWS file
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "user.db"; con = sqlite3.connect(f); con.execute("CREATE TABLE precious(x)"); con.commit(); con.close()
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{f}")
    p = subprocess.run([sys.executable, str(ROOT / "scripts/reset_db.py")], env=env, capture_output=True, text=True, cwd=d)
    con = sqlite3.connect(f); left = con.execute("SELECT name FROM sqlite_master WHERE name='precious'").fetchall(); con.close()
    rec("HDEWS-013", f"reset_db on a non-HDEWS sqlite file -> rc={p.returncode}; table 'precious' survives: {bool(left)}")
