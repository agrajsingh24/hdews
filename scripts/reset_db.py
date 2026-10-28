"""Delete the local SQLite database and reseed it. Refuses to run in production or against PostgreSQL."""
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from app.config import load_settings
from app.db import Database
from app.seed import seed

if __name__ == "__main__":
    settings = load_settings()
    if settings.is_production:
        sys.exit("Refusing to reset: HDEWS_ENV=production.")
    db = Database(settings.database_url)
    if db.dialect != "sqlite":
        sys.exit("reset_db.py only resets SQLite databases. For PostgreSQL, drop and recreate the database, then run seed_demo_data.py.")
    for suffix in ("", "-wal", "-shm"):
        p = Path(db.path + suffix)
        if p.exists():
            p.unlink()
    print(f"Removed {db.path}")
    seed(Database(settings.database_url))
