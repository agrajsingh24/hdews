"""Start HDEWS: apply migrations, load the demo dataset into an empty database (when allowed), then serve.

Cross-platform (Windows, macOS, Linux, containers); used by the Docker image and scripts/run_dev.sh.

Environment:
  HOST            interface to bind (default 127.0.0.1; the Docker image sets 0.0.0.0)
  PORT            port (default 8000; hosting platforms such as Render set this)
  HDEWS_SEED_DEMO auto | true | false. auto (default) seeds an EMPTY database in development/test/demo and
                  never in production. A database that already has data is never reseeded.
Any start-up problem (bad configuration, refused seed, default passwords on a hosted instance) exits with a
non-zero code and a message, instead of being hidden.
"""
from __future__ import annotations

import os
import sys

import _bootstrap  # noqa: F401
from app.config import REPO_ROOT, Settings, load_settings
from app.db import Database
from app.seed import SeedRefused, seed


def prepare(settings: Settings) -> str:
    db = Database(settings.database_url)
    try:
        applied = db.migrate()
        with db.tx() as tx:
            populated = bool(tx.scalar("SELECT COUNT(*) FROM sites"))
        mode = os.environ.get("HDEWS_SEED_DEMO", "auto").strip().lower()
        if mode not in ("auto", "true", "false"):
            raise ValueError("HDEWS_SEED_DEMO must be auto, true or false")
        if populated:
            status = "existing database kept"
        elif mode == "true" or (mode == "auto" and not settings.is_production):
            seed(db, environment=settings.app_env)
            status = "empty database: demo dataset loaded"
        else:
            status = "empty database: demo dataset NOT loaded (create accounts with scripts/manage_users.py)"
    finally:
        db.close()
    return f"migrations applied: {', '.join(applied) or 'none pending'}; {status}"


def main() -> int:
    try:
        settings = load_settings()
        print(f"HDEWS start-up (HDEWS_ENV={settings.app_env}): {prepare(settings)}", flush=True)
    except (SeedRefused, RuntimeError, ValueError) as exc:
        print(f"HDEWS start-up refused: {exc}", file=sys.stderr, flush=True)
        return 1
    if not (settings.frontend_dist / "index.html").exists():
        print("Warning: frontend/dist is missing; run scripts/build_frontend.sh. The API will still start.", file=sys.stderr)
    import uvicorn
    # proxy_headers is off so that CLIENT_IP_SOURCE is the single, explicit rule for client addresses.
    uvicorn.run("app.main:factory", factory=True, app_dir=str(REPO_ROOT / "backend"),
                host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")),
                proxy_headers=False, log_level=os.environ.get("LOG_LEVEL", "info"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
