"""Run the browser end-to-end scenarios against a real server on an isolated temporary database.

Phases: main (A-E + UI checks) -> restart server on the same DB (F) -> production-mode server (G).
Requires Node.js and Playwright with Chromium (`npm i -g playwright && npx playwright install chromium`).
Usage: python e2e/run_e2e.py [--shots DIR] [--out e2e/results.json]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def start(env, port):
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:factory", "--factory", "--app-dir", "backend",
                             "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return proc
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("server exited: " + proc.stderr.read()[-2000:])
            time.sleep(0.2)
    raise RuntimeError("server did not start")


def stop(proc):
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_phase(phase, env):
    r = subprocess.run(["node", str(ROOT / "e2e" / "scenarios.js"), phase], env=env, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"phase {phase} crashed: {r.stderr[-3000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=None)
    ap.add_argument("--out", default=str(ROOT / "e2e" / "results.json"))
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="hdews-e2e-"))
    if not (ROOT / "frontend" / "dist" / "js" / "main.js").exists():
        raise SystemExit("frontend/dist is missing: run ./scripts/build_frontend.sh first")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp}/e2e.db", "HDEWS_ENV": "development",
           "HDEWS_DEMO_PASSWORD": "e2e-strong-pass-123", "FIELD_GATEWAY_INGEST_KEY": "e2e-ingest-key",
           "ENABLE_BACKGROUND_REASSESSMENT": "true", "LLM_PROVIDER": "none", "LLM_API_KEY": ""}
    node_env = {**os.environ, "BASE": f"http://127.0.0.1:{args.port}", "PASSWORD": env["HDEWS_DEMO_PASSWORD"],
                "INGEST_KEY": env["FIELD_GATEWAY_INGEST_KEY"], "SHOTS": args.shots or ""}
    if args.shots:
        Path(args.shots).mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_demo_data.py")], env=env, check=True, capture_output=True)
    results, started = [], time.time()
    srv = start(env, args.port)
    try:
        results += run_phase("main", node_env)
    finally:
        stop(srv)
    srv = start(env, args.port)  # restart on the same database
    try:
        time.sleep(2)  # let the background loop resume simulated telemetry
        results += run_phase("restart", node_env)
    finally:
        stop(srv)
    srv = start({**env, "HDEWS_ENV": "production"}, args.port)
    try:
        results += run_phase("production", node_env)
    finally:
        stop(srv)
    shutil.rmtree(tmp, ignore_errors=True)
    total = sum(len(r["checks"]) for r in results)
    failed = [(r["scenario"], c) for r in results for c in r["checks"] if not c["ok"]]
    summary = {"scenarios": len(results), "scenarios_passed": sum(r["ok"] for r in results), "checks": total,
               "checks_failed": len(failed), "seconds": round(time.time() - started, 1), "results": results}
    Path(args.out).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    for r in results:
        print(("PASS " if r["ok"] else "FAIL ") + r["scenario"] + f"  ({sum(c['ok'] for c in r['checks'])}/{len(r['checks'])} checks)")
    for scn, c in failed:
        print(f"   x [{scn}] {c['name']}: {c['detail']}")
    print(f"{summary['scenarios_passed']}/{summary['scenarios']} scenarios, {total - len(failed)}/{total} checks passed in {summary['seconds']} s")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
