"""Delete the local HDEWS SQLite database and reseed the demo dataset.

Safety (HDEWS-013): refuses in production, refuses PostgreSQL, refuses any SQLite file that is not
an HDEWS database, and refuses to discard non-simulated (observed/imported) observations unless
--force is given. Usage: python scripts/reset_db.py [--force]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from app.config import load_settings
from app.db import Database
from app.seed import seed


def check_resettable(path: Path, force: bool) -> str | None:
    """Return a refusal reason, or None if the file may be deleted."""
    if not path.exists():
        return None
    try:
        # as_uri() percent-encodes "#", "?", "%" and handles Windows drive paths (file:///C:/...) (HDEWS-039).
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not {"schema_migrations", "sites", "observations", "audit_log"} <= tables:
                return f"{path} is not an HDEWS database (expected HDEWS tables were not found); it was left untouched."
            real = conn.execute("SELECT COUNT(*) FROM observations WHERE origin <> 'SIMULATED'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return f"{path} could not be read as SQLite ({exc}); it was left untouched."
    if real and not force:
        return (f"{path} contains {real} non-simulated observation(s). Re-run with --force to discard them, "
                "or back the file up first.")
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="discard observed/imported observations too")
    args = parser.parse_args(argv)
    settings = load_settings()
    if settings.is_production:
        print("Refusing to reset: HDEWS_ENV=production.", file=sys.stderr)
        return 2
    db = Database(settings.database_url)
    if db.dialect != "sqlite" or db.path == ":memory:":
        print("reset_db.py only resets SQLite database files. For PostgreSQL, drop and recreate the database, "
              "then run seed_demo_data.py.", file=sys.stderr)
        return 2
    reason = check_resettable(Path(db.path), args.force)
    if reason:
        print(f"Refusing to reset: {reason}", file=sys.stderr)
        return 2
    for suffix in ("", "-wal", "-shm"):
        p = Path(db.path + suffix)
        if p.exists():
            p.unlink()
    print(f"Removed {db.path}")
    seed(Database(settings.database_url), environment=settings.app_env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
