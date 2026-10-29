"""Operator CLI for HDEWS accounts. Every change is written to the audit log.

  python scripts/manage_users.py list
  python scripts/manage_users.py create USERNAME --role reviewer --name "Duty reviewer"
  python scripts/manage_users.py set-password USERNAME
  python scripts/manage_users.py disable USERNAME
  python scripts/manage_users.py enable USERNAME

Passwords are read from the HDEWS_NEW_PASSWORD environment variable if set, otherwise from a hidden prompt.
They are never accepted as command-line arguments (those appear in process lists and shell history).
Changing a password or disabling an account revokes that user's existing sessions.
Works in every HDEWS_ENV, including production (where the demo seed is refused), so it is also how the
first real administrator is created.
"""
import argparse
import getpass
import os
import re
import sys
import uuid

import _bootstrap  # noqa: F401
from app import clock
from app.config import load_settings
from app.db import Database
from app.security import ROLES, hash_password
from app.seed import KNOWN_DEFAULT_PASSWORDS, MIN_HOSTED_PASSWORD_LENGTH
from app.services import audit

ACTOR = {"id": None, "display_name": "manage_users.py (operator CLI)", "role": "admin_cli"}


def _password() -> str:
    pw = os.environ.get("HDEWS_NEW_PASSWORD")
    if pw is None:
        pw = getpass.getpass("New password: ")
        if getpass.getpass("Repeat: ") != pw:
            raise SystemExit("Passwords do not match.")
    if len(pw) < MIN_HOSTED_PASSWORD_LENGTH or pw in KNOWN_DEFAULT_PASSWORDS:
        raise SystemExit(f"Password must be at least {MIN_HOSTED_PASSWORD_LENGTH} characters and not a documented default.")
    return pw


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    c = sub.add_parser("create")
    c.add_argument("username")
    c.add_argument("--role", required=True, choices=ROLES)
    c.add_argument("--name", required=True)
    for name in ("set-password", "disable", "enable"):
        sub.add_parser(name).add_argument("username")
    args = p.parse_args(argv)
    db = Database(load_settings().database_url)
    db.migrate()
    with db.tx() as tx:
        if args.cmd == "list":
            for u in tx.all("SELECT username, display_name, role, status FROM users ORDER BY username"):
                print(f"{u['username']:16} {u['role']:9} {u['status']:9} {u['display_name']}")
            return 0
        username = args.username.strip().lower()
        user = tx.one("SELECT * FROM users WHERE username = ?", (username,))
        if args.cmd == "create":
            if user:
                print(f"User '{username}' already exists.", file=sys.stderr)
                return 2
            if not re.fullmatch(r"[a-z0-9._-]{3,64}", username):
                print("Username must be 3-64 characters: a-z, 0-9, '.', '_' or '-'.", file=sys.stderr)
                return 2
            uid = "u_" + uuid.uuid4().hex[:12]
            tx.insert("users", {"id": uid, "username": username, "display_name": args.name.strip()[:120],
                                "role": args.role, "password_hash": hash_password(_password()), "status": "active",
                                "created_at": clock.now_iso()})
            audit.record(tx, "user.created", "user", uid, {"username": username, "role": args.role}, ACTOR)
            print(f"Created {username} ({args.role}).")
            return 0
        if not user:
            print(f"No user '{username}'.", file=sys.stderr)
            return 2
        if args.cmd == "set-password":
            tx.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(_password()), user["id"]))
            tx.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
            audit.record(tx, "user.password_changed", "user", user["id"], {"username": username, "sessions_revoked": True}, ACTOR)
            print(f"Password changed for {username}; existing sessions revoked.")
        else:
            status = "disabled" if args.cmd == "disable" else "active"
            tx.execute("UPDATE users SET status = ? WHERE id = ?", (status, user["id"]))
            if status == "disabled":
                tx.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
            audit.record(tx, f"user.{args.cmd}d", "user", user["id"], {"username": username}, ACTOR)
            print(f"{username} is now {status}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
