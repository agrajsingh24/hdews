"""Regression tests for defects found in the second audit pass (HDEWS-031 … ).

Each test was run against the code before its fix and failed; see docs/BUG_AUDIT_REPORT.md.
"""
import json
from datetime import timedelta

from app import clock
from app.db import Database
from app.security import hash_token
from tests.conftest import ingest, now_iso


def _apply(client, h, preset, site="SNP-05"):
    r = client.post("/api/demo/scenario", headers=h, json={"site_ids": [site], "preset": preset})
    assert r.status_code == 200, r.text
    return r.json()


def _factor(assessment, key):
    return next(f for f in assessment["factors"] if f["key"] == key)


# ---------------------------------------------------------------------------------------------
# HDEWS-031: upgrading a database from migration 001 left existing push sources with a NULL
# site scope, so every reading from an existing gateway was rejected after the upgrade.
def test_upgrade_keeps_existing_gateway_able_to_write(tmp_path, env):
    from app.db import MIGRATIONS_DIR
    url = f"sqlite:///{tmp_path}/old.db"
    db = Database(url)
    # Build a database at schema version 001 only, as the original prototype shipped it.
    with db.tx() as tx:
        tx.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        tx.script((MIGRATIONS_DIR / "sqlite" / "001_initial.sql").read_text(encoding="utf-8"))
        tx.execute("INSERT INTO schema_migrations VALUES ('001_initial', '2026-10-01T00:00:00Z')")
        now = clock.now_iso()
        tx.execute("INSERT INTO data_sources (id, name, source_type, origin, access_mode, description, ingest_key_hash) "
                   "VALUES ('GW', 'Old gateway', 'iot_gateway', 'OBSERVED', 'push_api', 'pre-existing', ?)", (hash_token("k"),))
        tx.execute("INSERT INTO data_sources (id, name, source_type, origin, access_mode, description) "
                   "VALUES ('FILE', 'Old import', 'incident_inventory', 'IMPORTED', 'file_import', 'pre-existing')")
        for sid in ("A", "B"):
            tx.execute("INSERT INTO sites (id, name, district, state, latitude, longitude, hazards, description, "
                       "location_note, config, created_at, updated_at) VALUES (?, ?, 'D', 'S', 30, 79, '[\"landslide\"]', "
                       "'', '', '{}', ?, ?)", (sid, sid, now, now))
    db.migrate()
    with db.tx() as tx:
        gw = tx.one("SELECT ingest_site_scope FROM data_sources WHERE id = 'GW'")
        file_src = tx.one("SELECT ingest_site_scope FROM data_sources WHERE id = 'FILE'")
    # Existing push sources keep the access they had before the upgrade (every site); others get none.
    assert sorted(json.loads(gw["ingest_site_scope"])) == ["A", "B"]
    assert file_src["ingest_site_scope"] is None
    db.close()


# ---------------------------------------------------------------------------------------------
# HDEWS-032: idempotency keys were unique across *all* sources, so a second gateway that used the
# same key scheme (e.g. message counters) had its readings silently discarded as "duplicates".
def test_idempotency_keys_are_scoped_per_source(client, database, auth):
    with database.tx() as tx:
        tx.execute("INSERT INTO data_sources (id, name, source_type, origin, access_mode, description, enabled, "
                   "health_status, ingest_key_hash, ingest_site_scope) VALUES ('FIELD-GATEWAY-02', 'Second gateway', "
                   "'iot_gateway', 'OBSERVED', 'push_api', 'test', 1, 'UNKNOWN', ?, ?)",
                   (hash_token("second-key"), json.dumps(["SNP-05"])))
    t = now_iso(client)
    a = ingest(client, [{"sensor_id": "AGM-03-SOIL", "observed_at": t, "value": 31.0, "idempotency_key": "msg-1"}])
    b = ingest(client, [{"sensor_id": "SNP-05-SOIL", "observed_at": t, "value": 40.0, "idempotency_key": "msg-1"}],
               key="second-key", source="FIELD-GATEWAY-02")
    assert a.json()["accepted"] == 1
    assert b.json() == {"accepted": 1, "duplicates": 0, "rejected": [], "sites": ["SNP-05"]}, b.json()
    # A genuine retry from the same source is still deduplicated.
    retry = ingest(client, [{"sensor_id": "SNP-05-SOIL", "observed_at": t, "value": 40.0, "idempotency_key": "msg-1"}],
                   key="second-key", source="FIELD-GATEWAY-02")
    assert retry.json()["duplicates"] == 1 and retry.json()["accepted"] == 0
    with database.tx() as tx:
        rows = tx.all("SELECT source_id, value FROM observations WHERE origin = 'OBSERVED' ORDER BY source_id")
    assert [(r["source_id"], r["value"]) for r in rows] == [("FIELD-GATEWAY-01", 31.0), ("FIELD-GATEWAY-02", 40.0)]


# ---------------------------------------------------------------------------------------------
# HDEWS-033: a gateway reading at an off-grid time on a sensor that also has simulated readings
# was combined with them: the 24 h displacement was computed as (observed latest − simulated
# value 24 h earlier), a meaningless difference that produced a HIGH landslide assessment.
def test_change_indicators_never_mix_observed_and_simulated_series(client, auth, database):
    _apply(client, auth["analyst"], "normal")
    ref = clock.parse(now_iso(client))
    # A real extensometer reports its own (different) datum: 31.2 mm cumulative, a few minutes off-grid.
    t = clock.iso(ref - timedelta(minutes=3))
    r = ingest(client, [{"sensor_id": "SNP-05-EXT", "observed_at": t, "value": 31.2, "idempotency_key": "ext-1"}])
    assert r.json()["accepted"] == 1
    a = client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()["assessments"]
    ls = next(x for x in a if x["hazard"] == "landslide")
    disp = _factor(ls, "displacement_24h_mm")
    # Before the fix: value ≈ 19 mm (31.2 observed − ~12 simulated) → level high → tier HIGH.
    assert disp["value"] is None or abs(disp["value"]) < 5, disp
    assert disp["origins"] in ([], ["OBSERVED"]), disp
    assert ls["risk_tier"] != "HIGH"
    assert any("mixed" in n.lower() for n in ls["reliability_notes"]), ls["reliability_notes"]


def test_rain_accumulation_does_not_add_observed_readings_to_simulated_ones(client, auth):
    _apply(client, auth["analyst"], "increasing_rainfall")
    a0 = client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()["assessments"]
    sim_rain = _factor(next(x for x in a0 if x["hazard"] == "flash_flood"), "rain_1h_mm")["value"]
    ref = clock.parse(now_iso(client))
    ingest(client, [{"sensor_id": "SNP-05-RAIN", "observed_at": clock.iso(ref - timedelta(minutes=7)), "value": 9.0,
                     "idempotency_key": "rain-1"}])
    a1 = client.post("/api/sites/SNP-05/assess", headers=auth["analyst"]).json()["assessments"]
    rain = _factor(next(x for x in a1 if x["hazard"] == "flash_flood"), "rain_1h_mm")
    # Before the fix: simulated total + 9 mm. Now only the observed series is used, and it is incomplete.
    assert rain["value"] != round(sim_rain + 9.0, 1), rain
    assert rain["origins"] == ["OBSERVED"] and rain["status"] == "incomplete", rain


# ---------------------------------------------------------------------------------------------
# HDEWS-034: the overview's hourly rainfall chart summed every stored reading, so duplicate
# readings from two origins were double-counted there (the engine had been fixed, the view not).
def test_overview_rain_chart_does_not_double_count(client, auth, database):
    _apply(client, auth["analyst"], "increasing_rainfall")
    before = client.get("/api/overview", headers=auth["viewer"]).json()["rain_hourly"]["series"]["SNP-05"]
    with database.tx() as tx:
        rows = tx.all("SELECT * FROM observations WHERE sensor_id = 'SNP-05-RAIN' AND observed_at > ? ORDER BY observed_at",
                      (clock.iso(clock.now() - timedelta(hours=2)),))
    r = ingest(client, [{"sensor_id": "SNP-05-RAIN", "observed_at": o["observed_at"], "value": o["value"],
                         "idempotency_key": f"dup-{o['id']}"} for o in rows])
    assert r.json()["accepted"] == len(rows) > 0
    rh = client.get("/api/overview", headers=auth["viewer"]).json()["rain_hourly"]
    after = rh["series"]["SNP-05"]
    # Before the fix the newest hour read 21.0 mm instead of 16.9 mm. No hour may be inflated, and the
    # chart states which single origin it shows (observed readings now exist, so only those are used).
    assert all(a <= b + 1e-9 for a, b in zip(after, before)), (before, after)
    assert after[-1] == before[-1]
    assert rh["origin"]["SNP-05"] == "OBSERVED"


def test_set_ingest_scope_script(tmp_path, env):
    """The operator tool for narrowing a gateway's scope (HDEWS-031 follow-up) validates input and is audited."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    from app.seed import seed
    url = f"sqlite:///{tmp_path}/s.db"
    seed(Database(url), quiet=True)
    script = Path(__file__).resolve().parents[2] / "scripts" / "set_ingest_scope.py"
    run = lambda *a: subprocess.run([sys.executable, str(script), *a], env=dict(os.environ, DATABASE_URL=url),
                                    capture_output=True, text=True)
    assert "AGM-03" in run("FIELD-GATEWAY-01").stdout
    assert run("FIELD-GATEWAY-01", "NOPE-99").returncode == 2
    assert run("SIM-GATEWAY", "AGM-03").returncode == 2          # not a push source
    assert run("FIELD-GATEWAY-01", "SNP-05").returncode == 0
    with Database(url).tx() as tx:
        assert json.loads(tx.scalar("SELECT ingest_site_scope FROM data_sources WHERE id = 'FIELD-GATEWAY-01'")) == ["SNP-05"]
        ev = tx.one("SELECT details FROM audit_log WHERE event_type = 'data_source.scope_changed'")
        assert json.loads(ev["details"])["after"] == ["SNP-05"]
        assert audit_valid(tx)


def audit_valid(tx):
    from app.services import audit
    return audit.verify_chain(tx)["valid"]


# ---------------------------------------------------------------------------------------------
# HDEWS-035: after downtime, the simulated gateway's catch-up wrote readings for the downtime with
# received_at in the past, claiming HDEWS had received data while it was not running.
def test_catch_up_after_downtime_records_true_receipt_time(client, auth, database):
    from app.services import simulator
    _apply(client, auth["analyst"], "normal")
    restart = clock.now() + timedelta(hours=3)
    clock.set_frozen_now(restart)
    with database.tx() as tx:
        written = simulator.tick(tx)
        rows = tx.all("SELECT observed_at, received_at FROM observations WHERE site_id = 'SNP-05' AND origin = 'SIMULATED' "
                      "AND observed_at > ?", (clock.iso(restart - timedelta(hours=3)),))
    assert written > 0 and rows
    assert all(r["received_at"] >= clock.iso(restart) for r in rows), rows[:3]
    # Observation times still span the downtime (the gateway buffered them); only receipt is truthful.
    assert min(r["observed_at"] for r in rows) < clock.iso(restart - timedelta(hours=2))


# ---------------------------------------------------------------------------------------------
# HDEWS-036: a complete outage at a site (rain gauge included) raised no alert at all. The data-gap
# rule required *observed* rain ≥ 10 mm/h as proof of adverse weather, which is impossible to obtain
# when the rain gauge itself is down — the worst-case blackout produced nothing in the review queue.
def _alerts(client, h, site="SNP-05"):
    return client.get(f"/api/alerts?status=open&site_id={site}", headers=h).json()["items"]


def test_total_outage_including_rain_gauge_raises_data_gap_alert(client, auth):
    r = client.post("/api/demo/scenario", headers=auth["analyst"], json={
        "site_ids": ["SNP-05"], "preset": "rising_landslide_indicators",
        "overrides": {"offline_sensors": ["rain_gauge", "soil_moisture", "extensometer", "river_stage"], "outage_minutes": 420}})
    assert all(a["risk_tier"] == "INSUFFICIENT_DATA" for a in r.json()["assessments"])
    alerts = _alerts(client, auth["viewer"])
    assert {(a["kind"], a["hazard"]) for a in alerts} == {("DATA_QUALITY", "landslide"), ("DATA_QUALITY", "flash_flood")}
    assert all("cannot be ruled out" in a["title"] for a in alerts), [a["title"] for a in alerts]
    assert all(a["severity"] == "DATA_GAP" for a in alerts)  # never presented as a hazard alert


def test_no_data_gap_alert_when_rain_gauge_shows_fair_weather(client, auth):
    """The fix must not spam: a soil-sensor outage under observed dry weather stays a dashboard state only."""
    client.post("/api/demo/scenario", headers=auth["analyst"], json={
        "site_ids": ["SNP-05"], "preset": "normal", "overrides": {"offline_sensors": ["soil_moisture"], "outage_minutes": 420}})
    assert _alerts(client, auth["viewer"]) == []
