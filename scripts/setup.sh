#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd frontend
npx --yes pnpm@11.25.0 install --frozen-lockfile --ignore-scripts
node node_modules/vite/bin/vite.js build
echo 'Setup complete. Run bash scripts/start.sh and open http://127.0.0.1:8765'
