"""Create the schema and load the documented demo dataset (simulated telemetry, demo users, incidents)."""
import _bootstrap  # noqa: F401
from app.config import load_settings
from app.db import Database
from app.seed import seed

if __name__ == "__main__":
    settings = load_settings()
    seed(Database(settings.database_url))
