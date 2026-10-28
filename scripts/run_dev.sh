#!/usr/bin/env bash
# Start HDEWS locally: backend API + built frontend on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d frontend/dist ] || ./scripts/build_frontend.sh
python3 -c "
import sys; sys.path.insert(0, 'backend')
from app.config import load_settings; from app.db import Database
db = Database(load_settings().database_url); db.migrate()
with db.tx() as tx: n = tx.scalar('SELECT COUNT(*) FROM sites')
sys.exit(0 if n else 3)" || python3 scripts/seed_demo_data.py
exec python3 -m uvicorn app.main:factory --factory --app-dir backend --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
