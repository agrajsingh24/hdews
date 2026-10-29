"""Hash-chained audit log: tamper detection, append-only enforcement, concurrency, restart."""
import sqlite3
import threading

import pytest

from app.db import Database
from app.seed import seed
from app.services import audit

SYS = {"id": None, "display_name": "test", "role": "system"}


def unlocked(db):
    """Simulate a privileged attacker: drop the append-only triggers first."""
    with db.tx() as tx:
        tx.execute("DROP TRIGGER audit_log_no_update")
        tx.execute("DROP TRIGGER audit_log_no_delete")


def verify(db):
    with db.tx() as tx:
        return audit.verify_chain(tx)


def seqs(db):
    with db.tx() as tx:
        return [r["seq"] for r in tx.all("SELECT seq FROM audit_log ORDER BY seq")]


def test_fresh_chain_is_valid_and_reports_head_hash(database):
    v = verify(database)
    assert v["valid"] and v["events_checked"] == len(seqs(database)) and len(v["head_hash"]) == 64


def test_hash_calculation_and_linkage(database):
    with database.tx() as tx:
        rows = tx.all("SELECT * FROM audit_log ORDER BY seq")
    prev = audit.GENESIS
    for r in rows:
        content = {k: r[k] for k in ("event_id", "occurred_at", "actor_id", "actor_name", "actor_role", "event_type",
                                     "entity_type", "entity_id", "details")}
        assert r["prev_hash"] == prev and r["hash"] == audit._digest(prev, content)
        prev = r["hash"]


@pytest.mark.parametrize("statement", ["UPDATE audit_log SET actor_name = 'x'", "DELETE FROM audit_log",
                                       "DELETE FROM audit_log WHERE seq = 1"])
def test_append_only_enforced_by_database(database, statement):
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with database.tx() as tx:
            tx.execute(statement)
    assert verify(database)["valid"]


@pytest.mark.parametrize("where", ["first", "middle", "last"])
def test_edited_event_detected(database, where):
    unlocked(database)
    s = seqs(database)
    target = {"first": s[0], "middle": s[len(s) // 2], "last": s[-1]}[where]
    with database.tx() as tx:
        tx.execute("UPDATE audit_log SET details = '{\"tampered\":true}' WHERE seq = ?", (target,))
    v = verify(database)
    assert not v["valid"] and v["broken_at_seq"] == target and v["head_hash"] is None


def test_deleted_middle_event_detected(database):
    unlocked(database)
    s = seqs(database)
    with database.tx() as tx:
        tx.execute("DELETE FROM audit_log WHERE seq = ?", (s[3],))
    assert verify(database)["broken_at_seq"] == s[4]


def test_truncated_tail_detected(database):
    """HDEWS-018: deleting the newest events used to verify as valid."""
    unlocked(database)
    s = seqs(database)
    with database.tx() as tx:
        tx.execute("DELETE FROM audit_log WHERE seq >= ?", (s[-2],))
    v = verify(database)
    assert not v["valid"] and "missing" in v["reason"]


def test_entire_log_deleted_detected(database):
    unlocked(database)
    with database.tx() as tx:
        tx.execute("DELETE FROM audit_log")
    assert not verify(database)["valid"]


def test_reordered_events_detected(database):
    unlocked(database)
    s = seqs(database)
    with database.tx() as tx:
        a = tx.one("SELECT * FROM audit_log WHERE seq = ?", (s[2],))
        b = tx.one("SELECT * FROM audit_log WHERE seq = ?", (s[3],))
        for row, seq in ((a, s[3]), (b, s[2])):
            tx.execute("UPDATE audit_log SET event_id = ?, occurred_at = ?, event_type = ?, details = ?, prev_hash = ?, hash = ? "
                       "WHERE seq = ?", ("tmp" + str(seq), row["occurred_at"], row["event_type"], row["details"],
                                         row["prev_hash"], row["hash"], seq))
    assert not verify(database)["valid"]


def test_forged_inserted_event_detected(database):
    unlocked(database)
    with database.tx() as tx:
        last = tx.one("SELECT * FROM audit_log ORDER BY seq DESC LIMIT 1")
        tx.insert("audit_log", {**{k: last[k] for k in last if k != "seq"}, "event_id": "forged",
                                "details": '{"forged":true}'})
    assert not verify(database)["valid"]


def test_duplicate_event_id_rejected(database):
    with database.tx() as tx:
        row = audit.record(tx, "test.event", "test", None, {}, SYS)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        with database.tx() as tx:
            tx.insert("audit_log", {**row, "hash": "0" * 64})


def test_failed_transaction_leaves_no_audit_event(database):
    before = seqs(database)
    with pytest.raises(RuntimeError):
        with database.tx() as tx:
            audit.record(tx, "test.event", "test", None, {}, SYS)
            raise RuntimeError("abort")
    assert seqs(database) == before and verify(database)["valid"]


def test_concurrent_writers_keep_a_single_valid_chain(tmp_path, env):
    db = Database(f"sqlite:///{tmp_path}/a.db")
    seed(db, quiet=True)

    def writer(n):
        for i in range(20):
            with db.tx() as tx:
                audit.record(tx, "test.concurrent", "test", f"{n}-{i}", {"i": i}, SYS)
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    other = Database(f"sqlite:///{tmp_path}/a.db")  # a separate handle, as after a restart
    v = verify(other)
    assert v["valid"]
    with other.tx() as tx:
        assert tx.scalar("SELECT COUNT(*) FROM audit_log WHERE event_type = 'test.concurrent'") == 120
        assert tx.scalar("SELECT COUNT(DISTINCT prev_hash) FROM audit_log") == tx.scalar("SELECT COUNT(*) FROM audit_log")


def test_deletion_with_rewritten_hashes_detected_by_sequence_gap(database):
    """An attacker who deletes an event and recomputes every later hash defeats the hash check;
    the AUTOINCREMENT sequence gap still exposes the deletion (SQLite)."""
    unlocked(database)
    s = seqs(database)
    with database.tx() as tx:
        tx.execute("DELETE FROM audit_log WHERE seq = ?", (s[3],))
        prev = tx.one("SELECT hash FROM audit_log WHERE seq = ?", (s[2],))["hash"]
        for row in tx.all("SELECT * FROM audit_log WHERE seq > ? ORDER BY seq", (s[3],)):
            content = {k: row[k] for k in ("event_id", "occurred_at", "actor_id", "actor_name", "actor_role", "event_type",
                                           "entity_type", "entity_id", "details")}
            new = audit._digest(prev, content)
            tx.execute("UPDATE audit_log SET prev_hash = ?, hash = ? WHERE seq = ?", (prev, new, row["seq"]))
            prev = new
    v = verify(database)
    assert not v["valid"] and "gap" in v["reason"] and v["broken_at_seq"] == s[4]
