"""Database: initialisation, migrations, constraints, rollback, persistence, seed/reset safety, production guards."""
import os
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import db as dbmod
from app.config import load_settings
from app.db import Database
from app.main import create_app
from app.seed import SeedRefused, seed
from app.services import alerts as svc
from app.services import assessments, audit, simulator
from tests.conftest import PASSWORD, login

REPO = Path(__file__).resolve().parents[2]
ADMIN = {"id": "u_admin", "display_name": "Demo Administrator", "role": "admin"}


def test_empty_database_initialises_and_migrations_are_idempotent(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/x.db")
    assert db.migrate() == ["001_initial", "002_ingest_scope", "003_query_indexes", "004_action_sequence", "005_idempotency_per_source"]
    assert db.migrate() == []
    with db.tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM schema_migrations") == 5


def test_upgrade_from_001_preserves_existing_data(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript((dbmod.MIGRATIONS_DIR / "sqlite" / "001_initial.sql").read_text(encoding="utf-8"))
    conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_migrations VALUES ('001_initial', '2026-01-01T00:00:00Z')")
    conn.execute("INSERT INTO data_sources (id, name, source_type, origin, access_mode, description) "
                 "VALUES ('OLD', 'Old source', 'iot_gateway', 'OBSERVED', 'push_api', 'pre-existing')")
    conn.commit()
    conn.close()
    db = Database(f"sqlite:///{path}")
    assert db.migrate() == ["002_ingest_scope", "003_query_indexes", "004_action_sequence", "005_idempotency_per_source"]
    with db.tx() as tx:
        row = tx.one("SELECT * FROM data_sources WHERE id = 'OLD'")
    # HDEWS-031: an existing push source keeps its pre-upgrade access (all sites; none exist in this DB).
    # The original version of this test asserted NULL, i.e. it encoded the defect.
    assert row["description"] == "pre-existing" and json.loads(row["ingest_site_scope"]) == []


def test_failed_migration_is_rolled_back(tmp_path, monkeypatch):
    mig = tmp_path / "migrations"
    shutil.copytree(dbmod.MIGRATIONS_DIR, mig)
    (mig / "sqlite" / "999_broken.sql").write_text("CREATE TABLE half_done (x INTEGER);\nTHIS IS NOT SQL;\n", encoding="utf-8")
    monkeypatch.setattr(dbmod, "MIGRATIONS_DIR", mig)
    db = Database(f"sqlite:///{tmp_path}/m.db")
    with pytest.raises(sqlite3.OperationalError):
        db.migrate()
    with db.tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name = 'half_done'") == 0
        assert {r["version"] for r in tx.all("SELECT version FROM schema_migrations")} == {"001_initial", "002_ingest_scope", "003_query_indexes", "004_action_sequence", "005_idempotency_per_source"}


def test_foreign_keys_and_check_constraints_enforced(database):
    bad = [
        ("INSERT INTO sensors (id, site_id, sensor_type, metric, unit, expected_interval_s, source_id, label) "
         "VALUES ('x', 'NO-SITE', 'rain_gauge', 'rain_mm', 'mm', 900, 'SIM-GATEWAY', 'x')"),
        ("INSERT INTO observations (sensor_id, site_id, source_id, metric, value, unit, observed_at, received_at, "
         "quality_status, origin, provenance) VALUES ('AGM-03-SOIL','AGM-03','SIM-GATEWAY','m',1,'u','t','t','great','SIMULATED','p')"),
        "UPDATE alerts SET status = 'CLOSED'",
        "INSERT INTO users (id, username, display_name, role, password_hash, created_at) VALUES ('u_admin','dup','d','admin','h','t')",
        "UPDATE sites SET latitude = 95 WHERE id = 'AGM-03'",
    ]
    with database.tx() as tx:
        simulator.apply_scenario(tx, ["SNP-05"], "rising_landslide_indicators", None, ADMIN)
        assessments.run_site(tx, "SNP-05", "t")
    for sql in bad:
        with pytest.raises(sqlite3.IntegrityError):
            with database.tx() as tx:
                tx.execute(sql)


def test_seed_refuses_to_run_twice(database):
    with pytest.raises(RuntimeError, match="already seeded"):
        seed(database, quiet=True)


def test_seed_refused_in_production(tmp_path, env):
    """HDEWS-012: production seeding created admin accounts with the documented demo password."""
    db = Database(f"sqlite:///{tmp_path}/p.db")
    with pytest.raises(SeedRefused):
        seed(db, quiet=True, environment="production")
    with db.tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM sqlite_master WHERE name = 'users'") == 0


def test_production_refuses_to_start_with_default_passwords(tmp_path, monkeypatch, env):
    monkeypatch.setenv("HDEWS_DEMO_PASSWORD", "hdews-demo")
    db = Database(f"sqlite:///{tmp_path}/d.db")
    seed(db, quiet=True)
    with pytest.raises(RuntimeError, match="default password"):
        create_app(load_settings(app_env="production", enable_background_reassessment=False), db)
    create_app(load_settings(app_env="development", enable_background_reassessment=False), db)  # dev is allowed


def test_restart_persistence_of_alert_workflow(tmp_path, env):
    """Scenario F at the data layer: state, history and audit chain survive a process restart."""
    from starlette.testclient import TestClient
    url = f"sqlite:///{tmp_path}/persist.db"
    seed(Database(url), quiet=True)
    settings = load_settings(database_url=url, enable_background_reassessment=False, app_env="test")
    with TestClient(create_app(settings)) as c:
        c.post("/api/demo/scenario", headers=login(c, "analyst"), json={"site_ids": ["SNP-05"], "preset": "rising_landslide_indicators"})
        r = login(c, "reviewer")
        aid = c.get("/api/alerts?site_id=SNP-05", headers=r).json()["items"][0]["id"]
        c.post(f"/api/alerts/{aid}/acknowledge", headers=r, json={"notes": "before restart"})
        c.post(f"/api/alerts/{aid}/actions", headers=r, json={"action_type": "field_verification", "notes": "go look", "assignee": "Team 1"})
        token = r
    with TestClient(create_app(settings)) as c:  # new app, new connections: a restart
        d = c.get(f"/api/alerts/{aid}", headers=token).json()  # sessions persist too
        assert d["alert"]["status"] == "ACTION_ASSIGNED"
        assert [a["action_type"] for a in d["actions"]] == ["acknowledge", "field_verification"]
        assert c.get("/api/audit-log/verify", headers=token).json()["valid"]


def _run_reset(db_path, *args):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}", "HDEWS_DEMO_PASSWORD": PASSWORD, "HDEWS_ENV": "development"}
    return subprocess.run([sys.executable, str(REPO / "scripts" / "reset_db.py"), *args], env=env, capture_output=True, text=True)


def test_reset_refuses_non_hdews_database(tmp_path):
    """HDEWS-013: reset_db deleted whatever SQLite file DATABASE_URL pointed at."""
    p = tmp_path / "user.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE precious (x)")
    c.commit()
    c.close()
    r = _run_reset(p)
    assert r.returncode == 2 and "not an HDEWS database" in r.stderr
    conn = sqlite3.connect(p)
    try:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'precious'").fetchone()
    finally:
        conn.close()


def test_reset_refuses_to_discard_observed_data_without_force(tmp_path, env):
    p = tmp_path / "h.db"
    db = Database(f"sqlite:///{p}")
    seed(db, quiet=True)
    with db.tx() as tx:
        tx.execute("INSERT INTO observations (sensor_id, site_id, source_id, metric, value, unit, observed_at, received_at, "
                   "quality_status, origin, provenance) VALUES ('AGM-03-SOIL','AGM-03','FIELD-GATEWAY-01','m',30,'% VWC',"
                   "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','good','OBSERVED','real gateway')")
    r = _run_reset(p)
    assert r.returncode == 2 and "non-simulated" in r.stderr
    r = _run_reset(p, "--force")
    assert r.returncode == 0, r.stderr
    with Database(f"sqlite:///{p}").tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM observations WHERE origin = 'OBSERVED'") == 0


def test_reset_refused_in_production(tmp_path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path}/z.db", "HDEWS_ENV": "production"}
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "reset_db.py")], env=env, capture_output=True, text=True)
    assert r.returncode == 2 and "production" in r.stderr


def test_relative_sqlite_path_resolves_to_repo_root():
    s = load_settings(database_url="sqlite:///backend/some.db")
    assert s.database_url == f"sqlite:///{REPO / 'backend' / 'some.db'}"


def test_invalid_database_url_rejected():
    with pytest.raises(ValueError):
        Database("mysql://x")


def test_postgres_runtime_path_is_blocked_without_driver():
    """The PostgreSQL schema was verified with psql; the runtime path needs psycopg, which is not installed here."""
    pytest.importorskip("psycopg", reason="psycopg not installed: PostgreSQL runtime path cannot be exercised")


def test_resolve_and_audit_are_atomic_on_file_database(tmp_path, env):
    db = Database(f"sqlite:///{tmp_path}/t.db")
    seed(db, quiet=True)
    with db.tx() as tx:
        simulator.apply_scenario(tx, ["SNP-05"], "rising_landslide_indicators", None, ADMIN)
        assessments.run_site(tx, "SNP-05", "t")
        aid = tx.scalar("SELECT id FROM alerts")
    with db.tx() as tx:
        svc.acknowledge(tx, aid, ADMIN, "")
    with pytest.raises(RuntimeError):
        with db.tx() as tx:
            svc.resolve(tx, aid, ADMIN, "exercise", "valid reason")
            raise RuntimeError("crash after resolve, before commit")
    with db.tx() as tx:
        assert svc.get(tx, aid)["status"] == "ACKNOWLEDGED"
        assert audit.verify_chain(tx)["valid"]
