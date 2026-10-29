import json, os, sys, math
from datetime import timedelta
sys.path.insert(0, ".")
os.environ["HDEWS_DEMO_PASSWORD"]="p"; os.environ["FIELD_GATEWAY_INGEST_KEY"]="k"
import tests.conftest as tc
from starlette.testclient import TestClient
from app.main import create_app
from app.config import load_settings
def make_client(db):
    return TestClient(create_app(load_settings(database_url="sqlite:///:memory:", enable_background_reassessment=False, app_env="test"), db), raise_server_exceptions=False)
from app.db import Database
from app.seed import seed
from app import clock
from app.services.risk_engine import merge_config, build_features, assess, validate_site_overrides
from tests.test_risk_engine import SENSORS, series, REF, SITE, normal, run

def hdr(c,u): return {"Authorization":"Bearer "+c.post("/api/auth/login",json={"username":u,"password":"p"}).json()["token"]}
db=Database("sqlite:///:memory:"); seed(db, quiet=True)
with make_client(db) as c:
    now=c.get("/api/health").json()["time"]
    H={"X-HDEWS-Ingest-Key":"k","content-type":"application/json"}
    # B1: Infinity reading breaks JSON endpoints
    r=c.post("/api/ingestion/FIELD-GATEWAY-01", content='{"readings":[{"sensor_id":"AGM-03-SOIL","observed_at":"%s","value":Infinity}]}'%now, headers=H)
    print("B1 ingest inf ->", r.status_code)
    v=hdr(c,"viewer")
    print("B1 overview ->", c.get("/api/overview",headers=v).status_code, " observations ->", c.get("/api/sites/AGM-03/observations?hours=1",headers=v).status_code)
    # B2: unit field silently ignored
    r=c.post("/api/ingestion/FIELD-GATEWAY-01", json={"readings":[{"sensor_id":"AGM-03-RIVER","observed_at":now,"value":9.8,"unit":"ft"}]}, headers=H)
    print("B2 unit=ft accepted? ->", r.status_code, r.json().get("accepted"))
    # B3: rain double counted when OBSERVED + SIMULATED share timestamps
    last=c.get("/api/sites/SNP-05/observations?hours=1",headers=v).json()
    rain=[s for s in last["series"] if s["sensor_type"]=="rain_gauge"][0]["points"]
    before=c.get("/api/sites/SNP-05",headers=v).json()["indicators"]["rain_1h_mm"]["value"]
    c.post("/api/ingestion/FIELD-GATEWAY-01", json={"readings":[{"sensor_id":"SNP-05-RAIN","observed_at":p["t"],"value":p["v"]} for p in rain]}, headers=H)
    after=c.get("/api/sites/SNP-05",headers=v).json()["indicators"]["rain_1h_mm"]["value"]
    print(f"B3 rain_1h before={before} after re-sending identical readings as OBSERVED={after}")
    # B4: body size unbounded
    big='{"readings":[' + ",".join(['{"sensor_id":"x","observed_at":"%s","value":1}'%now]*60000)+']}'
    r=c.post("/api/ingestion/FIELD-GATEWAY-01", content=big, headers=H); print("B4 %.1f MB body ->"%(len(big)/1e6), r.status_code)
    # B5: unknown scenario param silently ignored
    a=hdr(c,"analyst")
    r=c.post("/api/demo/scenario",headers=a,json={"site_ids":["AGM-03"],"overrides":{"rain_mmh":50}}); print("B5 typo param ->", r.status_code)
    # B6: threshold editor accepts bool / unknown key / inf
    ad=hdr(c,"admin")
    for ov in ({"landslide":{"rain_24h_mm":{"watch":True,"high":2}}},{"landslide":{"rain_24hr_mm":{"watch":1,"high":2}}}):
        print("B6", ov, "->", c.put("/api/sites/AGM-03/config",headers=ad,json={"overrides":ov}).status_code)
    print("B6 inf ->", c.put("/api/sites/AGM-03/config",headers={**ad,"content-type":"application/json"},content='{"overrides":{"landslide":{"rain_24h_mm":{"watch":1,"high":Infinity}}}}').status_code)
    # B7: any gateway key can write any site (no scope)
# B8: fresh-but-unusable readings make an old value look current
obs=normal(); old=series(lambda h: 45.0, end_offset_min=300)
bad=series(lambda h: 0.0, hours=4)
for o in bad: o["quality_status"]="bad"
obs["soil"]=sorted(old+bad,key=lambda o:o["observed_at"])
cfg=merge_config(None); f=build_features(SENSORS,obs,cfg,REF)
ind=f["indicators"]["soil_moisture_pct"]
print("B8 soil indicator status=%s value=%s as_of=%s (5h old) sensor state=%s"%(ind.status,ind.value,ind.as_of,f["health"]["soil"].state))
# B9: extensometer outage lowers apparent risk to LOW
obs=normal(); obs["ext"]=series(lambda h: 20-h*0.3)
r1=run("landslide",obs)
obs["ext"]=series(lambda h: 20-h*0.3, hours=30, end_offset_min=7*60)
r2=run("landslide",obs)
print("B9 displacement high:", r1["risk_tier"], r1["reliability"], "-> extensometer offline 7h:", r2["risk_tier"], r2["reliability"])
# B10: NaN value treated as normal
obs=normal(); obs["soil"]=series(lambda h: float("nan"))
r=run("landslide",obs); s=[x for x in r["factors"] if x["key"]=="soil_moisture_pct"][0]
print("B10 NaN soil -> level", s["level"], "status", s["status"], "tier", r["risk_tier"], r["reliability"])
# B11: lower-bound claimed when missing inputs cannot change tier
obs=normal(); obs["rain"]=series(lambda h: 2.0); obs["soil"]=series(lambda h: 46.0); obs["ext"]=[]
r=run("landslide",obs); print("B11 tier", r["risk_tier"], "lower_bound", r["tier_is_lower_bound"], "max", r["max_possible_tier"])
