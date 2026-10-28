"""Authentication and role-based access control (stdlib only).

Passwords: scrypt with a per-user random salt. Sessions: random bearer tokens;
only their SHA-256 hash is stored. Demo accounts are created by the seed script
and are labelled DEMO in the UI — replace with a real identity provider before
any non-demo deployment.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from . import clock
from .db import Tx

ROLES = ("viewer", "analyst", "reviewer", "admin")

# Permission -> roles allowed.
PERMISSIONS: dict[str, set[str]] = {
    "read": {"viewer", "analyst", "reviewer", "admin"},
    "run_assessment": {"analyst", "reviewer", "admin"},
    "run_scenario": {"analyst", "admin"},
    "alert_review": {"reviewer", "admin"},           # acknowledge, act, escalate, resolve
    "manage_config": {"admin"},
    "manage_sources": {"admin"},
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(tx: Tx, user_id: str, ttl_hours: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    expires = clock.iso(clock.now() + timedelta(hours=ttl_hours))
    tx.insert("sessions", {"token_hash": hash_token(token), "user_id": user_id,
                           "created_at": clock.now_iso(), "expires_at": expires})
    return token, expires


def user_for_token(tx: Tx, token: str) -> dict | None:
    row = tx.one(
        "SELECT u.id, u.username, u.display_name, u.role, u.status, s.expires_at FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (hash_token(token),))
    if not row or row["status"] != "active":
        return None
    if clock.parse(row["expires_at"]) <= clock.now():
        tx.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
        return None
    return row


def can(user: dict | None, permission: str) -> bool:
    return bool(user) and user["role"] in PERMISSIONS[permission]
