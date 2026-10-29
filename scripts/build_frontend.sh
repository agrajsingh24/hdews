#!/usr/bin/env bash
# Compile the TypeScript frontend into frontend/dist (served by the backend).
# Cross-platform equivalent (Windows too): cd frontend && npm install && npm run build
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npm run build
echo "Frontend built into frontend/dist"
