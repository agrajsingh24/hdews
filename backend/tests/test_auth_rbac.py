"""Authentication and server-side authorization, tested directly against the API (not the UI)."""
from datetime import timedelta

import pytest

from app import clock, security
from tests.conftest import PASSWORD, ROLES, counts, login

MUTATION_TABLES = ("alerts", "alert_actions", "observations", "assessments", "scenario_runs", "sites")


def _open_alert(client, auth):
    client.post("/api/demo/scenario", headers=auth["analyst"], json={"site_ids": ["SNP-05"], "preset": "rising_landslide_indicators"})
    return client.get("/api/alerts?status=open&site_id=SNP-05", headers=auth["viewer"]).json()["items"][0]["id"]


# (method, path template, body, permission)
SENSITIVE = [
    ("POST", "/api/alerts/{alert}/acknowledge", {"notes": "x"}, "alert_review"),
    ("POST", "/api/alerts/{alert}/actions", {"action_type": "note", "notes": "hello"}, "alert_review"),
    ("POST", "/api/alerts/{alert}/resolve", {"category": "exercise", "reason": "drill complete"}, "alert_review"),
    ("PUT", "/api/sites/AGM-03/config", {"overrides": {"landslide": {"rain_24h_mm": {"watch": 1, "high": 2}}}}, "manage_config"),
    ("POST", "/api/demo/scenario", {"site_ids": ["AGM-03"], "preset": "normal"}, "run_scenario"),
    ("POST", "/api/sites/AGM-03/assess", None, "run_assessment"),
]
READS = ["/api/overview", "/api/sites", "/api/sites/AGM-03", "/api/sites/AGM-03/observations", "/api/map/layers",
         "/api/assessments", "/api/alerts", "/api/incidents", "/api/data-sources", "/api/audit-log",
         "/api/audit-log/verify", "/api/evaluation", "/api/rules", "/api/demo/presets"]


@pytest.mark.parametrize("method,path,body,permission", SENSITIVE)
@pytest.mark.parametrize("role", ROLES)
def test_permission_matrix_enforced_server_side(client, auth, database, role, method, path, body, permission):
    alert = _open_alert(client, auth)
    allowed = role in security.PERMISSIONS[permission]
    before = counts(database, *MUTATION_TABLES)
    with database.tx() as tx:
        cfg_before = tx.scalar("SELECT config FROM sites WHERE id = 'AGM-03'")
        status_before = tx.scalar("SELECT status FROM alerts WHERE id = ?", (alert,))
    r = client.request(method, path.format(alert=alert), headers=auth[role], json=body)
    if allowed:
        assert r.status_code in (200, 409), r.text  # 409: valid permission, invalid state (e.g. resolve before ack)
    else:
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == "forbidden"
        assert counts(database, *MUTATION_TABLES) == before, "a denied request must not mutate data"
        with database.tx() as tx:
            assert tx.scalar("SELECT config FROM sites WHERE id = 'AGM-03'") == cfg_before
            assert tx.scalar("SELECT status FROM alerts WHERE id = ?", (alert,)) == status_before


@pytest.mark.parametrize("path", READS)
def test_every_read_endpoint_requires_auth_and_allows_viewer(client, auth, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401
    assert client.get(path, headers=auth["viewer"]).status_code == 200


@pytest.mark.parametrize("role", ROLES)
def test_login_succeeds_for_each_role_and_reports_permissions(client, role):
    r = client.post("/api/auth/login", json={"username": role, "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == role and len(body["token"]) >= 40
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"}).json()
    assert set(me["permissions"]) == {p for p, roles in security.PERMISSIONS.items() if role in roles}


@pytest.mark.parametrize("payload", [
    {"username": "reviewer", "password": "wrong"},
    {"username": "nobody", "password": PASSWORD},
    {"username": "REVIEWER ", "password": "wrong"},
])
def test_bad_credentials_get_identical_responses(client, payload):
    r = client.post("/api/auth/login", json=payload)
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "invalid_credentials", "message": "Username or password is incorrect."}}


def test_unknown_username_still_runs_password_hashing(client, monkeypatch):
    """HDEWS-019: unknown users must cost the same scrypt work (no username enumeration by timing)."""
    calls = []
    real = security.verify_password
    monkeypatch.setattr(security, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{}, {"username": "admin"}, {"password": "x"}, {"username": "", "password": ""},
                                     {"username": 5, "password": True}])
def test_missing_or_malformed_credentials(client, payload):
    assert client.post("/api/auth/login", json=payload).status_code == 422


def test_logout_invalidates_only_that_session(client):
    a, b = login(client, "reviewer"), login(client, "reviewer")
    client.post("/api/auth/logout", headers=a)
    assert client.get("/api/auth/me", headers=a).status_code == 401
    assert client.get("/api/auth/me", headers=b).status_code == 200


def test_expired_session_is_rejected_and_removed(client, database):
    h = login(client, "viewer")
    clock.set_frozen_now(clock.now() + timedelta(hours=13))  # TTL is 12 h
    assert client.get("/api/overview", headers=h).status_code == 401
    with database.tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM sessions WHERE token_hash = ?",
                         (security.hash_token(h["Authorization"][7:]),)) == 0


def test_disabled_account_cannot_log_in_or_use_existing_session(client, database):
    h = login(client, "analyst")
    with database.tx() as tx:
        tx.execute("UPDATE users SET status = 'disabled' WHERE username = 'analyst'")
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.post("/api/auth/login", json={"username": "analyst", "password": PASSWORD}).status_code == 401


def test_session_tokens_are_stored_hashed(client, database):
    h = login(client, "viewer")
    token = h["Authorization"][7:]
    with database.tx() as tx:
        stored = [r["token_hash"] for r in tx.all("SELECT token_hash FROM sessions")]
    assert token not in stored and security.hash_token(token) in stored


def test_login_rate_limit(client):
    codes = [client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_malformed_authorization_headers(client):
    for header in ("Bearer", "Basic abc", "bearer ", "Token x", "Bearer " + "a" * 5000):
        assert client.get("/api/overview", headers={"Authorization": header}).status_code == 401


def test_no_idor_on_nonexistent_resources(client, auth):
    for path in ("/api/alerts/al_doesnotexist", "/api/sites/../../etc/passwd", "/api/assessments/1 OR 1=1",
                 "/api/incidents/%27%3B%20DROP%20TABLE%20users%3B--"):
        r = client.get(path, headers=auth["viewer"])
        assert r.status_code == 404, (path, r.status_code)
    assert client.get("/api/sites", headers=auth["viewer"]).json()["total"] == 6  # tables intact


@pytest.mark.parametrize("stored", ["", "nonsense", "bcrypt$a$b", "scrypt$$", "scrypt$not-base64!$x"])
def test_malformed_stored_password_hash_never_verifies(stored):
    try:
        assert security.verify_password("anything", stored) is False
    except Exception as exc:  # pragma: no cover - would be a defect
        pytest.fail(f"verify_password raised {exc!r}")


def test_can_without_user_is_false():
    assert security.can(None, "read") is False


def test_login_with_corrupted_stored_hash_is_401_not_500(lenient_client, database):
    with database.tx() as tx:
        tx.execute("UPDATE users SET password_hash = 'scrypt$not-base64!$x' WHERE username = 'viewer'")
    r = lenient_client.post("/api/auth/login", json={"username": "viewer", "password": "anything"})
    assert r.status_code == 401
