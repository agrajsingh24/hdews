"""Performance smoke test on an enlarged dataset. Records measurements; asserts no latency targets.

Usage: python scripts/perf_smoke.py [--days 30] [--out docs/perf_results.json]
Builds a temporary SQLite database (never touches backend/hdews.db), adds N days of 15-min
telemetry for every sensor, a large audit log and assessment history, then measures endpoint
latency (sequential and concurrent), SQL statement counts per request, and query plans.
"""
import argparse
import json
import os
import platform
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import _bootstrap  # noqa: F401
from starlette.testclient import TestClient

from app import clock
from app.config import load_settings
from app.db import Database, Tx
from app.main import create_app
from app.seed import seed
from app.services import assessments, audit


def build(db: Database, days: int) -> dict:
    now = clock.now()
    with db.tx() as tx:
        sensors = tx.all("SELECT * FROM sensors")
        rows = 0
        for s in sensors:
            t = now - timedelta(days=days)
            stop = now - timedelta(hours=49)  # leave the seeded recent window alone
            while t < stop:
                tx.execute("INSERT INTO observations (sensor_id, site_id, source_id, metric, value, unit, observed_at, "
                           "received_at, quality_status, origin, provenance) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (s["id"], s["site_id"], s["source_id"], s["metric"], 1.0, s["unit"], clock.iso(t), clock.iso(t),
                            "good", "SIMULATED", "perf smoke history"))
                t += timedelta(minutes=15)
                rows += 1
        for i in range(20000):
            audit.record(tx, "perf.event", "test", str(i), {"i": i})
    for _ in range(40):  # 40 x 9 = 360 extra assessments, each with assessment.changed events when tiers flip
        with db.tx() as tx:
            assessments.run_all(tx, "perf")
    with db.tx() as tx:
        return {"observations": tx.scalar("SELECT COUNT(*) FROM observations"), "history_rows_added": rows,
                "audit_events": tx.scalar("SELECT COUNT(*) FROM audit_log"),
                "assessments": tx.scalar("SELECT COUNT(*) FROM assessments")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "docs" / "perf_results.json"))
    args = ap.parse_args()
    os.environ.setdefault("HDEWS_DEMO_PASSWORD", "perf-pass")
    tmp = tempfile.mkdtemp()
    url = f"sqlite:///{tmp}/perf.db"
    db = Database(url)
    t0 = time.perf_counter()
    seed(db, quiet=True)
    size = build(db, args.days)
    build_s = time.perf_counter() - t0

    statements = {"n": 0}
    real_execute = Tx.execute

    def counting(self, sql, params=()):
        statements["n"] += 1
        return real_execute(self, sql, params)
    Tx.execute = counting

    app = create_app(load_settings(database_url=url, enable_background_reassessment=False, app_env="test"))
    results = {}
    with TestClient(app) as c:
        h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"username": "analyst", "password": os.environ["HDEWS_DEMO_PASSWORD"]}).json()["token"]}
        endpoints = {
            "overview": ("GET", "/api/overview"), "site_detail": ("GET", "/api/sites/SNP-05"),
            "observations_24h": ("GET", "/api/sites/SNP-05/observations?hours=24"),
            "observations_168h": ("GET", "/api/sites/SNP-05/observations?hours=168"),
            "alerts_list": ("GET", "/api/alerts?status=all"), "assessments_list": ("GET", "/api/assessments"),
            "audit_page": ("GET", "/api/audit-log"), "audit_verify": ("GET", "/api/audit-log/verify"),
            "map_layers": ("GET", "/api/map/layers"), "sites_list": ("GET", "/api/sites"),
            "assess_site": ("POST", "/api/sites/SNP-05/assess"),
            "simulator_apply": ("POST", "/api/demo/scenario"),
        }
        for name, (method, path) in endpoints.items():
            body = {"site_ids": ["SNP-05"], "preset": "increasing_rainfall"} if name == "simulator_apply" else None
            times = []
            for _ in range(7):
                statements["n"] = 0
                s = time.perf_counter()
                r = c.request(method, path, headers=h, json=body)
                times.append((time.perf_counter() - s) * 1000)
                assert r.status_code == 200, (name, r.status_code, r.text[:200])
            results[name] = {"median_ms": round(statistics.median(times), 1), "max_ms": round(max(times), 1),
                             "sql_statements": statements["n"]}
        conc = []

        def hit(_):
            s = time.perf_counter()
            assert c.get("/api/overview", headers=h).status_code == 200
            return (time.perf_counter() - s) * 1000
        s = time.perf_counter()
        with ThreadPoolExecutor(8) as pool:
            conc = list(pool.map(hit, range(40)))
        results["overview_concurrent_8x40"] = {"wall_s": round(time.perf_counter() - s, 2),
                                               "median_ms": round(statistics.median(conc), 1), "max_ms": round(max(conc), 1)}
    Tx.execute = real_execute
    plans = {}
    with Database(url).tx() as tx:
        for label, sql in {
            "tier_changes": "SELECT occurred_at FROM audit_log WHERE event_type = 'assessment.changed' ORDER BY seq DESC LIMIT 15",
            "assessments_unfiltered": "SELECT id FROM assessments ORDER BY assessed_at DESC LIMIT 50",
            "site_window": "SELECT id FROM observations WHERE site_id = 'SNP-05' AND observed_at > '2026' AND received_at <= '2027'",
            "sensor_latest": "SELECT MAX(observed_at) FROM observations WHERE sensor_id = 'SNP-05-RAIN' AND received_at <= '2027'",
        }.items():
            plans[label] = " | ".join(r["detail"] for r in tx.all("EXPLAIN QUERY PLAN " + sql))
    out = {"environment": {"python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(),
                           "database": "SQLite (file, WAL)", "client": "Starlette TestClient (in-process, no network)"},
           "dataset": {**size, "history_days": args.days, "build_seconds": round(build_s, 1)},
           "results": results, "query_plans": plans,
           "note": "Smoke measurements on one machine; not latency targets or a load test."}
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
