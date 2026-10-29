#!/usr/bin/env bash
# Start HDEWS locally on http://127.0.0.1:8000 (Windows: `python scripts\start.py`).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f frontend/dist/index.html ] || ./scripts/build_frontend.sh
exec python3 scripts/start.py
