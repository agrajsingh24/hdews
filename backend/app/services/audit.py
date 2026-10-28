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
    prev_hash = GENESIS
    count = 0
    for row in tx.all("SELECT * FROM audit_log ORDER BY seq"):
        content = {k: row[k] for k in ("event_id", "occurred_at", "actor_id", "actor_name", "actor_role",
                                       "event_type", "entity_type", "entity_id", "details")}
        if row["prev_hash"] != prev_hash or row["hash"] != _digest(prev_hash, content):
            return {"valid": False, "events_checked": count, "broken_at_seq": row["seq"]}
        prev_hash = row["hash"]
        count += 1
    return {"valid": True, "events_checked": count, "broken_at_seq": None}
