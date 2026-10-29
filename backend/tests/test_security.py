"""Security properties: headers, production lock-down, no outbound contact, secrets hygiene, CORS."""
import socket
import subprocess
from pathlib import Path

import pytest

from tests.conftest import login, make_client

REPO = Path(__file__).resolve().parents[2]


def test_security_headers_on_api_and_static(client):
    for path in ("/api/health", "/"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "script-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_no_cors_by_default(client):
    r = client.options("/api/overview", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_only_for_configured_origins(database):
    with make_client(database, cors_origins=("https://ops.example",)) as c:
        ok = c.options("/api/overview", headers={"Origin": "https://ops.example", "Access-Control-Request-Method": "GET"})
        bad = c.options("/api/overview", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://ops.example"
    assert "access-control-allow-origin" not in bad.headers


def test_production_mode_disables_demo_routes_and_hints(database):
    """Scenario G."""
    with make_client(database, app_env="production") as c:
        h = login(c, "admin")
        assert c.post("/api/demo/scenario", headers=h, json={"site_ids": ["SNP-05"], "preset": "normal"}).status_code == 404
        assert c.get("/api/demo/presets", headers=h).status_code == 404
        meta = c.get("/api/meta").json()
        assert meta["demo_endpoints"] is False and meta["demo_login_hint"] is None


def test_alert_actions_make_no_network_connections(client, auth, monkeypatch):
    """Escalations and 'test notifications' are recorded only: nothing may contact anyone."""
    attempts = []

    def no_network(*a, **k):
        attempts.append(a)
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["SNP-05"], "preset": "rising_landslide_indicators"})
    aid = client.get("/api/alerts?site_id=SNP-05", headers=auth["viewer"]).json()["items"][0]["id"]
    r = auth["reviewer"]
    client.post(f"/api/alerts/{aid}/acknowledge", headers=r, json={})
    for action in ("escalation", "test_notification", "field_verification"):
        assert client.post(f"/api/alerts/{aid}/actions", headers=r,
                           json={"action_type": action, "notes": "check it", "assignee": "Duty officer"}).status_code == 200
    client.post(f"/api/alerts/{aid}/resolve", headers=r, json={"category": "exercise", "reason": "drill done"})
    assert attempts == []


def test_no_secrets_or_databases_tracked_in_git():
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
    assert ".env" not in files
    assert not [f for f in files if f.endswith((".db", ".sqlite", ".pem", ".key"))]
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line.startswith(("LLM_API_KEY=",)):
            assert line.strip() == "LLM_API_KEY="


def test_api_responses_never_include_password_hashes_or_ingest_keys(client, auth):
    blob = "".join(client.get(p, headers=auth["admin"]).text for p in
                   ("/api/data-sources", "/api/auth/me", "/api/audit-log?limit=200", "/api/sites/SNP-05", "/api/overview"))
    assert "scrypt$" not in blob and "ingest_key_hash" not in blob and "password_hash" not in blob


def test_frontend_has_no_html_injection_sinks():
    src = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "frontend" / "src").rglob("*.ts"))
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in src, sink


@pytest.mark.parametrize("path", ["/../backend/hdews.db", "/%2e%2e/backend/app/config.py", "/..%2f..%2fetc/passwd"])
def test_static_files_do_not_allow_path_traversal(client, path):
    r = client.get(path)
    assert r.status_code == 404 or "<!doctype html>" in r.text.lower()
    assert "SQLite" not in r.text and "load_settings" not in r.text
