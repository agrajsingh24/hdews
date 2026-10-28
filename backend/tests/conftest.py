import pytest
from starlette.testclient import TestClient

from app import clock
from app.config import load_settings
from app.db import Database
from app.main import create_app
from app.seed import seed

INGEST_KEY = "test-ingest-key-123"
PASSWORD = "test-pass"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("HDEWS_DEMO_PASSWORD", PASSWORD)
    monkeypatch.setenv("FIELD_GATEWAY_INGEST_KEY", INGEST_KEY)
    clock.set_frozen_now(None)
    yield
    clock.set_frozen_now(None)


@pytest.fixture()
def database(env):
    db = Database("sqlite:///:memory:")
    seed(db, quiet=True)
    return db


def make_client(database, **overrides):
    settings = load_settings(database_url="sqlite:///:memory:", enable_background_reassessment=False,
                             app_env=overrides.pop("app_env", "test"), llm_provider="none", llm_api_key="", **overrides)
    return TestClient(create_app(settings, database))


@pytest.fixture()
def client(database):
    with make_client(database) as c:
        yield c


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def auth(client):
    return {role: login(client, role) for role in ("admin", "analyst", "reviewer", "viewer")}
