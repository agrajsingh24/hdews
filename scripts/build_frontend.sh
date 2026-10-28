#!/usr/bin/env bash
# Compile the TypeScript frontend into frontend/dist (served by the backend).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
rm -rf dist
npx --no-install tsc -p . 2>/dev/null || tsc -p .
cp public/index.html public/styles.css dist/
echo "Frontend built into frontend/dist"
