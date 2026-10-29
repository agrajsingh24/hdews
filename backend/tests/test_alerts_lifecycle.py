"""Candidate-alert lifecycle at the service level: transitions, dedup, data-gap alerts, atomicity, concurrency."""
import sqlite3
import threading

import pytest

from app.services import alerts as svc
from app.services import assessments, audit, simulator
from tests.conftest import counts

ADMIN = {"id": "u_admin", "display_name": "Demo Administrator", "role": "admin"}
REVIEWER = {"id": "u_reviewer", "display_name": "Demo Duty Reviewer", "role": "reviewer"}


def scenario(db, preset, site="SNP-05", overrides=None):
    with db.tx() as tx:
        simulator.apply_scenario(tx, [site], preset, overrides, ADMIN)
        return assessments.run_site(tx, site, "test")


def open_alerts(db, **where):
    clause = " AND ".join(f"{k} = ?" for k in where) or "1 = 1"
    with db.tx() as tx:
        return tx.all(f"SELECT * FROM alerts WHERE status <> 'RESOLVED' AND {clause}", list(where.values()))


def high_alert(db):
    scenario(db, "rising_landslide_indicators")
    return open_alerts(db, site_id="SNP-05", hazard="landslide", kind="HAZARD")[0]["id"]


def do(db, fn, *args):
    with db.tx() as tx:
        return fn(tx, *args)


ACK = (svc.acknowledge, REVIEWER, "ok")
ACT = (svc.add_action, REVIEWER, "field_verification", "check slope", "Team 1")
NOTE = (svc.add_action, REVIEWER, "note", "observation", None)
RESOLVE = (svc.resolve, REVIEWER, "false_alarm", "sensor drift confirmed")

# state -> operation -> expected resulting status (None = rejected with TransitionError)
MATRIX = {
    "REVIEW_REQUIRED": {"ack": "ACKNOWLEDGED", "act": None, "note": "REVIEW_REQUIRED", "resolve": None},
    "ACKNOWLEDGED": {"ack": None, "act": "ACTION_ASSIGNED", "note": "ACKNOWLEDGED", "resolve": "RESOLVED"},
    "ACTION_ASSIGNED": {"ack": None, "act": "ACTION_ASSIGNED", "note": "ACTION_ASSIGNED", "resolve": "RESOLVED"},
    "RESOLVED": {"ack": None, "act": None, "note": None, "resolve": None},
}
OPS = {"ack": ACK, "act": ACT, "note": NOTE, "resolve": RESOLVE}
PATH = {"REVIEW_REQUIRED": [], "ACKNOWLEDGED": ["ack"], "ACTION_ASSIGNED": ["ack", "act"], "RESOLVED": ["ack", "resolve"]}


@pytest.mark.parametrize("state", MATRIX)
@pytest.mark.parametrize("op", OPS)
def test_transition_matrix(database, state, op):
    aid = high_alert(database)
    for step in PATH[state]:
        fn, *args = OPS[step]
        do(database, fn, aid, *args)
    fn, *args = OPS[op]
    expected = MATRIX[state][op]
    before = counts(database, "alert_actions", "audit_log")
    if expected is None:
        with pytest.raises(svc.TransitionError):
            do(database, fn, aid, *args)
        assert counts(database, "alert_actions", "audit_log") == before, "a rejected transition must leave no trace"
        assert do(database, svc.get, aid)["status"] == state
    else:
        assert do(database, fn, aid, *args)["status"] == expected


@pytest.mark.parametrize("bad", [("escalation", "", None), ("escalation", "x", "  "), ("bogus", "x", "y")])
def test_action_validation(database, bad):
    aid = high_alert(database)
    do(database, svc.acknowledge, aid, REVIEWER, "")
    action, notes, assignee = bad
    with pytest.raises(svc.TransitionError):
        do(database, svc.add_action, aid, REVIEWER, action, notes, assignee)


@pytest.mark.parametrize("category,reason", [("false_alarm", ""), ("false_alarm", "    "), ("closed", "a valid reason")])
def test_resolution_requires_category_and_reason(database, category, reason):
    aid = high_alert(database)
    do(database, svc.acknowledge, aid, REVIEWER, "")
    with pytest.raises(svc.TransitionError):
        do(database, svc.resolve, aid, REVIEWER, category, reason)


def test_resolved_alert_cannot_be_reopened_and_new_condition_opens_new_alert(database):
    aid = high_alert(database)
    do(database, svc.acknowledge, aid, REVIEWER, "")
    do(database, svc.resolve, aid, REVIEWER, "exercise", "demo drill done")
    with pytest.raises(svc.TransitionError):
        do(database, svc.acknowledge, aid, REVIEWER, "")
    with database.tx() as tx:
        assessments.run_site(tx, "SNP-05", "test")
    new = open_alerts(database, site_id="SNP-05", hazard="landslide", kind="HAZARD")
    assert len(new) == 1 and new[0]["id"] != aid


def test_test_notification_is_recorded_only(database):
    aid = high_alert(database)
    do(database, svc.acknowledge, aid, REVIEWER, "")
    do(database, svc.add_action, aid, REVIEWER, "test_notification", "drill", "Duty officer")
    with database.tx() as tx:
        note = tx.scalar("SELECT notes FROM alert_actions WHERE action_type = 'test_notification'")
    assert note.startswith("[DEMO TEST NOTIFICATION") and "nothing was sent" in note


def test_dedup_links_reassessments_to_one_alert(database):
    aid = high_alert(database)
    for _ in range(3):
        with database.tx() as tx:
            assessments.run_site(tx, "SNP-05", "test")
    rows = open_alerts(database, site_id="SNP-05", hazard="landslide", kind="HAZARD")
    assert [r["id"] for r in rows] == [aid] and rows[0]["trigger_count"] == 4
    with database.tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM alert_assessments WHERE alert_id = ?", (aid,)) == 4


def test_database_enforces_one_open_alert_per_condition(database):
    aid = high_alert(database)
    row = do(database, svc.get, aid)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        with database.tx() as tx:
            tx.insert("alerts", {**row, "id": "al_dup"})


def test_concurrent_assessments_create_a_single_alert(database, tmp_path, monkeypatch):
    from app.db import Database
    from app.seed import seed
    db = Database(f"sqlite:///{tmp_path}/c.db")
    seed(db, quiet=True)
    with db.tx() as tx:
        simulator.apply_scenario(tx, ["SNP-05"], "rising_landslide_indicators", None, ADMIN)
    errors = []

    def worker():
        try:
            with db.tx() as tx:
                assessments.run_site(tx, "SNP-05", "concurrent")
        except Exception as exc:  # pragma: no cover - reported via assertion
            errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len(open_alerts(db, site_id="SNP-05", hazard="landslide", kind="HAZARD")) == 1


def test_failure_during_transition_rolls_back(database, monkeypatch):
    aid = high_alert(database)
    before = counts(database, "alert_actions", "audit_log")

    def broken(*a, **k):
        raise RuntimeError("audit store unavailable")
    monkeypatch.setattr(audit, "record", broken)
    with pytest.raises(RuntimeError):
        do(database, svc.acknowledge, aid, REVIEWER, "x")
    assert do(database, svc.get, aid)["status"] == "REVIEW_REQUIRED"
    assert counts(database, "alert_actions", "audit_log") == before


def test_alert_references_the_assessment_and_its_evidence(database):
    aid = high_alert(database)
    alert = do(database, svc.get, aid)
    with database.tx() as tx:
        a = assessments.hydrate(tx.one("SELECT * FROM assessments WHERE id = ?", (alert["latest_assessment_id"],)))
        ids = a["evidence_observation_ids"]
        found = tx.scalar(f"SELECT COUNT(*) FROM observations WHERE id IN ({','.join('?' * len(ids))})", ids)
    assert a["hazard"] == alert["hazard"] == "landslide" and a["risk_tier"] == "HIGH"
    assert found == len(ids) > 0


def test_data_gap_alert_is_distinct_from_hazard_alert(database):
    scenario(database, "sensor_outage_adverse_weather")
    rows = open_alerts(database, site_id="SNP-05")
    kinds = {(r["hazard"], r["kind"]) for r in rows}
    assert ("landslide", "DATA_QUALITY") in kinds
    dq = [r for r in rows if r["kind"] == "DATA_QUALITY"]
    assert all(r["severity"] == "DATA_GAP" and "data gap" in r["title"].lower() for r in dq)
    assert all(r["kind"] != "HAZARD" for r in dq)


def test_no_data_gap_alert_without_adverse_conditions(database):
    scenario(database, "normal", overrides={"offline_sensors": ["soil_moisture"], "outage_minutes": 420})
    assert not open_alerts(database, site_id="SNP-05", kind="DATA_QUALITY")


def test_dedup_after_recovery_and_relapse(database):
    scenario(database, "sensor_outage_adverse_weather")
    first = {r["id"] for r in open_alerts(database, site_id="SNP-05", kind="DATA_QUALITY")}
    scenario(database, "normal")  # recovered; alerts stay open until a human resolves them
    scenario(database, "sensor_outage_adverse_weather")  # relapse while still open: no duplicates
    again = {r["id"] for r in open_alerts(database, site_id="SNP-05", kind="DATA_QUALITY")}
    assert again == first


def test_actions_within_the_same_second_keep_recorded_order(database):
    """HDEWS-026: actions sharing a created_at second were ordered by a random id."""
    from app import clock
    clock.set_frozen_now(clock.now())
    try:
        aid = high_alert(database)
        do(database, svc.acknowledge, aid, REVIEWER, "")
        for i in range(8):
            do(database, svc.add_action, aid, REVIEWER, "note", f"note {i}", None)
        with database.tx() as tx:
            rows = tx.all("SELECT action_type, notes, seq FROM alert_actions WHERE alert_id = ? ORDER BY seq", (aid,))
        assert [r["seq"] for r in rows] == list(range(1, 10))
        assert [r["notes"] for r in rows[1:]] == [f"note {i}" for i in range(8)]
    finally:
        clock.set_frozen_now(None)
