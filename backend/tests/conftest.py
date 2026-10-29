import os

import pytest

# Tests must not depend on a developer's local .env (set before anything loads settings; inherited by
# subprocesses the tests start).
os.environ["HDEWS_DOTENV"] = "0"
from starlette.testclient import TestClient

from app import clock
from app.config import load_settings
from app.db import Database
from app.main import create_app
from app.seed import seed

INGEST_KEY = "test-ingest-key-123"
PASSWORD = "test-pass"
ROLES = ("admin", "analyst", "reviewer", "viewer")


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("HDEWS_DEMO_PASSWORD", PASSWORD)
    monkeypatch.setenv("FIELD_GATEWAY_INGEST_KEY", INGEST_KEY)
    monkeypatch.delenv("HDEWS_ENV", raising=False)
    clock.set_frozen_now(None)
    yield
    clock.set_frozen_now(None)


@pytest.fixture()
def database(env):
    db = Database("sqlite:///:memory:")
    seed(db, quiet=True)
    yield db
    db.close()


def make_client(database, raise_server_exceptions=True, **overrides):
    settings = load_settings(database_url="sqlite:///:memory:", enable_background_reassessment=False,
                             app_env=overrides.pop("app_env", "test"), llm_provider=overrides.pop("llm_provider", "none"),
                             llm_api_key=overrides.pop("llm_api_key", ""), **overrides)
    return TestClient(create_app(settings, database), raise_server_exceptions=raise_server_exceptions)


@pytest.fixture()
def client(database):
    with make_client(database) as c:
        yield c


@pytest.fixture()
def lenient_client(database):
    """Client that turns unhandled server errors into HTTP 500 responses, as a real server would."""
    with make_client(database, raise_server_exceptions=False) as c:
        yield c


def login(client, username, password=PASSWORD):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def auth(client):
    return {role: login(client, role) for role in ROLES}


def ingest(client, readings, key=INGEST_KEY, source="FIELD-GATEWAY-01"):
    return client.post(f"/api/ingestion/{source}", json={"readings": readings}, headers={"X-HDEWS-Ingest-Key": key})


def now_iso(client):
    return client.get("/api/health").json()["time"]


def counts(db, *tables):
    with db.tx() as tx:
        return {t: tx.scalar(f"SELECT COUNT(*) FROM {t}") for t in tables}
