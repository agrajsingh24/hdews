import sys, os, inspect; sys.path.insert(0,'.')
from datetime import datetime, timezone
from app.services.risk_engine import assess, merge_config
from app.services.risk_engine.features import Indicator, SensorHealth
REF=datetime(2026,7,15,12,tzinfo=timezone.utc); T="2026-07-15T12:00:00Z"
def ind(k,v,st="available",s="r"): return Indicator(k,k,"u",v,st,s,T,[1],origins={"SIMULATED"})
kw={"usable_state":"FRESH"} if "usable_state" in inspect.signature(SensorHealth).parameters else {}
h={s:SensorHealth(s,s,s,"FRESH",T,T,0,0,False,900,1.0,"good","SIMULATED",1,**kw) for s in ("r","v")}
i={"rain_1h_mm":ind("rain_1h_mm",10),"rain_3h_mm":ind("rain_3h_mm",31,"incomplete"),"river_level_m":ind("river_level_m",1.0,s="v"),"river_rise_1h_m":ind("river_rise_1h_m",0.35,s="v")}
r=assess({"id":"S","name":"S"},"flash_flood",i,h,merge_config(None),REF)
print(os.environ["TREE"], "-> tier",r["risk_tier"],"max_possible",r["max_possible_tier"],"tier_is_lower_bound",r["tier_is_lower_bound"],"| summary says understate:", "understate" in r["summary"])
