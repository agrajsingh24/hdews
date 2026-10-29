import os, sys, sqlite3, subprocess, time, statistics
sys.path.insert(0, "."); sys.path.insert(0, "..")
SP=os.environ["SP"]
from app.db import Database
from app.seed import seed
from app.config import load_settings
from app.services import explanations, audit
# B12 production seed with default password
env=dict(os.environ, HDEWS_ENV="production", DATABASE_URL=f"sqlite:///{SP}/prod.db"); env.pop("HDEWS_DEMO_PASSWORD",None)
if os.path.exists(f"{SP}/prod.db"): os.remove(f"{SP}/prod.db")
r=subprocess.run([sys.executable,"../scripts/seed_demo_data.py"],env=env,capture_output=True,text=True)
print("B12 production seed rc=",r.returncode, "|", (r.stdout.strip().splitlines() or [""])[-1][:90])
# B13 reset_db on a non-HDEWS sqlite file
p=f"{SP}/userdata.db"; c=sqlite3.connect(p); c.execute("create table if not exists precious(x)"); c.execute("insert into precious values(1)"); c.commit(); c.close()
env=dict(os.environ, DATABASE_URL=f"sqlite:///{p}", HDEWS_DEMO_PASSWORD="p")
subprocess.run([sys.executable,"../scripts/reset_db.py"],env=env,capture_output=True,text=True)
c=sqlite3.connect(p); print("B13 'precious' table still exists after reset_db:", bool(c.execute("select name from sqlite_master where name='precious'").fetchall()))
# B15/B16 LLM
os.environ["HDEWS_DEMO_PASSWORD"]="p"
db=Database("sqlite:///:memory:"); seed(db,quiet=True)
with db.tx() as tx: row=tx.one("select * from assessments where risk_tier='ELEVATED' limit 1")
from app.services.assessments import hydrate
a=hydrate(row); s=load_settings(llm_provider="anthropic", llm_api_key="x")
try: explanations.explain(a,s,llm_call=lambda s,p: (_ for _ in ()).throw(AttributeError("bad shape"))); print("B15 handled")
except Exception as e: print("B15 unhandled provider error ->", type(e).__name__)
out=explanations.explain(a,s,llm_call=lambda s,p: "The risk tier is LOW and conditions are safe.")
print("B16 contradictory tier accepted:", out["method"]=="llm", "(actual tier", a["risk_tier"]+")")
out=explanations.explain(a,s,llm_call=lambda s,p: "Elevated. "*400); print("B16b 4000-char output accepted:", out["method"]=="llm")
# B18 audit tail truncation
with db.tx() as tx:
    n=tx.scalar("select count(*) from audit_log")
    tx.execute("drop trigger audit_log_no_delete"); tx.execute("delete from audit_log where seq=(select max(seq) from audit_log)")
    print("B18 after deleting the newest audit event:", audit.verify_chain(tx), "(was", n, "events)")
# B14 login timing
from app.security import verify_password, hash_password
