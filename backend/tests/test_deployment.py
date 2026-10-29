"""Deployment-readiness regressions (HDEWS-040 … 042): hosted configuration, client IPs behind a proxy,
account management without the demo seed, and the single start-up path used by Docker and developers."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.config import load_settings
from app.db import Database
from app.main import create_app
from app.seed import SeedRefused, seed

REPO = Path(__file__).resolve().parents[2]
STRONG = "a-strong-demo-pass-2026"


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HDEWS_", "FIELD_GATEWAY", "CLIENT_IP"))}
    env["HDEWS_DOTENV"] = "0"  # never read a developer's local .env
    env.update(extra)
    return env


# ---------------------------------------------------------------- HDEWS-040: environments
def test_unknown_environment_name_is_rejected():
    """A typo such as HDEWS_ENV=prod used to behave like development (simulator on, no secret checks)."""
    for bad in ("prod", "staging", ""):
        with pytest.raises(ValueError, match="HDEWS_ENV must be one of"):
            load_settings(app_env=bad)
    assert load_settings(app_env="demo").is_hosted and load_settings(app_env="production").is_hosted
    assert not load_settings(app_env="development").is_hosted


@pytest.mark.parametrize("password", [None, "short", "hdews-demo", "change-me-demo-password"])
def test_hosted_demo_refuses_missing_short_or_default_password(monkeypatch, password):
    monkeypatch.delenv("HDEWS_DEMO_PASSWORD", raising=False)
    if password is not None:
        monkeypatch.setenv("HDEWS_DEMO_PASSWORD", password)
    with pytest.raises(SeedRefused, match="HDEWS_DEMO_PASSWORD"):
        seed(Database("sqlite:///:memory:"), quiet=True, environment="demo")


def test_hosted_demo_refuses_placeholder_ingest_key(monkeypatch):
    monkeypatch.setenv("HDEWS_DEMO_PASSWORD", STRONG)
    monkeypatch.setenv("FIELD_GATEWAY_INGEST_KEY", "change-me-ingest-key")
    with pytest.raises(SeedRefused, match="FIELD_GATEWAY_INGEST_KEY"):
        seed(Database("sqlite:///:memory:"), quiet=True, environment="demo")


def test_hosted_demo_seed_prints_no_secrets(monkeypatch, capsys):
    monkeypatch.setenv("HDEWS_DEMO_PASSWORD", STRONG)
    monkeypatch.delenv("FIELD_GATEWAY_INGEST_KEY", raising=False)
    info = seed(Database("sqlite:///:memory:"), environment="demo")
    out = capsys.readouterr().out
    assert "HDEWS demo data seeded." in out
    assert STRONG not in out and info["ingest_key"] not in out


def test_hosted_demo_keeps_simulator_and_refuses_default_passwords(monkeypatch):
    monkeypatch.setenv("HDEWS_DEMO_PASSWORD", STRONG)
    db = Database("sqlite:///:memory:")
    seed(db, quiet=True, environment="demo")
    s = load_settings(database_url="sqlite:///:memory:", app_env="demo", enable_background_reassessment=False)
    assert s.demo_endpoints_active
    with TestClient(create_app(s, db)) as c:
        meta = c.get("/api/meta").json()
        assert meta["environment"] == "demo" and meta["demo_endpoints"] is True
        assert "hdews-demo" not in json.dumps(meta) and "operator" in meta["demo_login_hint"]
        tok = c.post("/api/auth/login", json={"username": "analyst", "password": STRONG}).json()["token"]
        r = c.post("/api/demo/scenario", headers={"Authorization": f"Bearer {tok}"}, json={"site_ids": ["AGM-03"], "preset": "normal"})
        assert r.status_code == 200
    # A database whose accounts use a documented default password must not be served in demo mode.
    weak = Database("sqlite:///:memory:")
    monkeypatch.setenv("HDEWS_DEMO_PASSWORD", "hdews-demo")
    seed(weak, quiet=True, environment="development")
    with pytest.raises(RuntimeError, match="HDEWS_ENV=demo"):
        create_app(s, weak)


# ---------------------------------------------------------------- HDEWS-041: client IP behind a proxy
def _login_until_limited(client, headers_for_attempt):
    codes = [client.post("/api/auth/login", json={"username": "viewer", "password": "wrong"},
                         headers=headers_for_attempt(i)).status_code for i in range(12)]
    return codes


def test_behind_proxy_one_user_cannot_exhaust_everyones_login_limit(database):
    """Default 'peer' mode: every request comes from the proxy's address, so 10 failed logins by one person
    lock out every other user. With x-forwarded-for-first, the limit applies per real client."""
    s_peer = load_settings(database_url="sqlite:///:memory:", app_env="test", enable_background_reassessment=False)
    with TestClient(create_app(s_peer, database)) as c:
        codes = _login_until_limited(c, lambda i: {"X-Forwarded-For": "203.0.113.7"})
        other = c.post("/api/auth/login", json={"username": "viewer", "password": "wrong"},
                       headers={"X-Forwarded-For": "198.51.100.9"}).status_code
    assert codes[-1] == 429 and other == 429  # the documented limitation of peer mode behind a proxy

    s_xff = load_settings(database_url="sqlite:///:memory:", app_env="test", enable_background_reassessment=False,
                          client_ip_source="x-forwarded-for-first")
    with TestClient(create_app(s_xff, database)) as c:
        codes = _login_until_limited(c, lambda i: {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
        other = c.post("/api/auth/login", json={"username": "viewer", "password": "wrong"},
                       headers={"X-Forwarded-For": "198.51.100.9, 10.0.0.1"}).status_code
    assert codes[-1] == 429 and other == 401


def test_client_ip_source_last_uses_the_hop_added_by_our_proxy(database):
    s = load_settings(database_url="sqlite:///:memory:", app_env="test", enable_background_reassessment=False,
                      client_ip_source="x-forwarded-for-last")
    with TestClient(create_app(s, database)) as c:
        # A client rotating a spoofed left-most value cannot escape the limit: the proxy-added hop is constant.
        codes = _login_until_limited(c, lambda i: {"X-Forwarded-For": f"192.0.2.{i}, 203.0.113.7"})
    assert codes[-1] == 429


def test_invalid_client_ip_source_rejected():
    with pytest.raises(ValueError, match="CLIENT_IP_SOURCE"):
        load_settings(client_ip_source="x-real-ip")


# ---------------------------------------------------------------- HDEWS-042: accounts without the demo seed
def _manage(url, *args, password=None):
    env = _env(DATABASE_URL=url)
    if password is not None:
        env["HDEWS_NEW_PASSWORD"] = password
    return subprocess.run([sys.executable, str(REPO / "scripts" / "manage_users.py"), *args], env=env,
                          capture_output=True, text=True, timeout=120)


def test_manage_users_bootstraps_production_and_rotates_passwords(tmp_path):
    url = f"sqlite:///{tmp_path}/p.db"
    assert _manage(url, "create", "ops-admin", "--role", "admin", "--name", "Ops admin", password="short").returncode != 0
    assert _manage(url, "create", "ops-admin", "--role", "admin", "--name", "Ops admin", password="hdews-demo").returncode != 0
    r = _manage(url, "create", "ops-admin", "--role", "admin", "--name", "Ops admin", password=STRONG)
    assert r.returncode == 0 and STRONG not in r.stdout + r.stderr
    assert _manage(url, "create", "ops-admin", "--role", "admin", "--name", "x", password=STRONG).returncode == 2
    assert _manage(url, "create", "Bad Name!", "--role", "admin", "--name", "x", password=STRONG).returncode == 2

    db = Database(url)
    s = load_settings(database_url=url, app_env="production", enable_background_reassessment=False)
    with TestClient(create_app(s, db)) as c:          # production starts: no default passwords present
        tok = c.post("/api/auth/login", json={"username": "ops-admin", "password": STRONG}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        assert c.get("/api/auth/me", headers=h).json()["user"]["role"] == "admin"
        assert _manage(url, "set-password", "ops-admin", password=STRONG + "-new").returncode == 0
        assert c.get("/api/auth/me", headers=h).status_code == 401      # old session revoked
        assert c.post("/api/auth/login", json={"username": "ops-admin", "password": STRONG}).status_code == 401
        assert _manage(url, "disable", "ops-admin").returncode == 0
        assert c.post("/api/auth/login", json={"username": "ops-admin", "password": STRONG + "-new"}).status_code == 401
    assert "ops-admin" in _manage(url, "list").stdout
    with db.tx() as tx:
        events = [r["event_type"] for r in tx.all("SELECT event_type FROM audit_log WHERE entity_type = 'user' ORDER BY seq")]
        from app.services import audit
        assert audit.verify_chain(tx)["valid"]
    assert ["user.created", "user.password_changed", "user.disabled"] == [e for e in events if e.startswith("user.") and e != "user.login"][:3]
    db.close()


# ---------------------------------------------------------------- start-up path (Docker / run_dev / Windows)
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_refuses_bad_configuration_loudly(tmp_path):
    """The old Docker command hid seed failures (`2>/dev/null || true`) and then served an empty database."""
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "start.py")], timeout=120, capture_output=True, text=True,
                       env=_env(HDEWS_ENV="demo", DATABASE_URL=f"sqlite:///{tmp_path}/d.db", PORT=str(_free_port())))
    assert r.returncode == 1 and "start-up refused" in r.stderr and "HDEWS_DEMO_PASSWORD" in r.stderr
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "start.py")], timeout=120, capture_output=True, text=True,
                       env=_env(HDEWS_ENV="prod", DATABASE_URL=f"sqlite:///{tmp_path}/d.db"))
    assert r.returncode == 1 and "HDEWS_ENV must be one of" in r.stderr


def test_start_serves_hosted_demo_and_keeps_data_across_restart(tmp_path):
    port = _free_port()
    env = _env(HDEWS_ENV="demo", HDEWS_DEMO_PASSWORD=STRONG, DATABASE_URL=f"sqlite:///{tmp_path}/d.db",
               HOST="127.0.0.1", PORT=str(port), ENABLE_BACKGROUND_REASSESSMENT="false")
    base = f"http://127.0.0.1:{port}"

    def run_once(check):
        p = subprocess.Popen([sys.executable, str(REPO / "scripts" / "start.py")], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for _ in range(150):
                try:
                    urllib.request.urlopen(base + "/api/health", timeout=1)
                    break
                except Exception:
                    if p.poll() is not None:
                        raise AssertionError(p.stdout.read())
                    time.sleep(0.2)
            return check()
        finally:
            p.terminate()
            try:
                out, _ = p.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
                out, _ = p.communicate()
            assert STRONG not in out  # the password never reaches the logs

    def call(path, body=None, token=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, resp.read()

    def first():
        status, headers, html = call("/")
        assert status == 200 and b"<div id=\"app\">" in html and "Content-Security-Policy" in headers
        tok = json.loads(call("/api/auth/login", {"username": "reviewer", "password": STRONG})[2])["token"]
        sites = json.loads(call("/api/sites", token=tok)[2])
        assert len(sites["items"]) == 6
        return json.loads(call("/api/audit-log/verify", token=tok)[2])["events_checked"]

    events_before = run_once(first)

    def second():
        tok = json.loads(call("/api/auth/login", {"username": "reviewer", "password": STRONG})[2])["token"]
        v = json.loads(call("/api/audit-log/verify", token=tok)[2])
        assert v["valid"] and v["events_checked"] > events_before  # same database, not reseeded (login added events)
        return v

    second_result = run_once(second)
    assert second_result["valid"]


def test_health_reports_deployed_version(client, monkeypatch):
    monkeypatch.delenv("HDEWS_VERSION", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert client.get("/api/health").json()["version"] is None
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    assert client.get("/api/health").json()["version"] == "abc123"
    monkeypatch.setenv("HDEWS_VERSION", "v-explicit")
    assert client.get("/api/health").json()["version"] == "v-explicit"
