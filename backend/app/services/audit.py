"""Append-only, hash-chained audit log.

Each event stores the SHA-256 of (previous hash + canonical event content), so any
edit to a stored event breaks the chain and is detected by `verify_chain`.
The database additionally rejects UPDATE/DELETE on the table via triggers.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from .. import clock
from ..db import Tx

GENESIS = "0" * 64
SYSTEM_ACTOR = {"id": None, "display_name": "HDEWS system", "role": "system"}


def _digest(prev_hash: str, content: dict) -> str:
    payload = prev_hash + json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def record(tx: Tx, event_type: str, entity_type: str, entity_id: str | None, details: dict,
           actor: dict | None = None) -> dict:
    actor = actor or SYSTEM_ACTOR
    if tx.dialect == "postgres":  # pragma: no cover - serialise chain appends across connections (untested: no driver)
        tx.execute("SELECT pg_advisory_xact_lock(4242001)")
    prev = tx.one("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1")
    prev_hash = prev["hash"] if prev else GENESIS
    content = {
        "event_id": uuid.uuid4().hex,
        "occurred_at": clock.now_iso(),
        "actor_id": actor.get("id"),
        "actor_name": actor.get("display_name", "unknown"),
        "actor_role": actor.get("role", "unknown"),
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": json.dumps(details, sort_keys=True, separators=(",", ":"), default=str),
    }
    row = {**content, "prev_hash": prev_hash, "hash": _digest(prev_hash, content)}
    tx.insert("audit_log", row)
    return row


def verify_chain(tx: Tx) -> dict:
    """Recompute the chain. Detects edited, deleted, inserted or reordered events.

    On SQLite it also detects removal of the newest events (tail truncation) and sequence gaps,
    using the AUTOINCREMENT high-water mark, which the hash chain alone cannot reveal (HDEWS-018).
    `head_hash` can be recorded outside the database (e.g. in a signed daily report) so that a
    privileged attacker rewriting the whole chain would also be detected.
    """
    prev_hash = GENESIS
    count = 0
    expected_seq = None
    for row in tx.all("SELECT * FROM audit_log ORDER BY seq"):
        content = {k: row[k] for k in ("event_id", "occurred_at", "actor_id", "actor_name", "actor_role",
                                       "event_type", "entity_type", "entity_id", "details")}
        if row["prev_hash"] != prev_hash or row["hash"] != _digest(prev_hash, content):
            return _result(False, count, row["seq"], "hash mismatch or broken link", prev_hash)
        if tx.dialect == "sqlite" and expected_seq is not None and row["seq"] != expected_seq:
            return _result(False, count, row["seq"], f"sequence gap before event #{row['seq']}", prev_hash)
        expected_seq = row["seq"] + 1
        prev_hash = row["hash"]
        count += 1
    if tx.dialect == "sqlite":
        high = tx.scalar("SELECT seq FROM sqlite_sequence WHERE name = 'audit_log'") or 0
        last = (expected_seq or 1) - 1
        if high != last:
            return _result(False, count, last + 1, f"events after #{last} are missing (high-water mark #{high})", prev_hash)
    return _result(True, count, None, None, prev_hash)


def _result(valid: bool, count: int, broken: int | None, reason: str | None, head: str) -> dict:
    return {"valid": valid, "events_checked": count, "broken_at_seq": broken, "reason": reason,
            "head_hash": head if valid else None}
