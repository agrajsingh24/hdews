"""Create the schema and load the documented demo dataset (simulated telemetry, demo users, incidents)."""
import _bootstrap  # noqa: F401
from app.config import load_settings
from app.db import Database
from app.seed import SeedRefused, seed

if __name__ == "__main__":
    settings = load_settings()
    try:
        seed(Database(settings.database_url), environment=settings.app_env)
    except (SeedRefused, RuntimeError) as exc:
        raise SystemExit(f"Not seeded: {exc}")
