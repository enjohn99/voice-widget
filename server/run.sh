#!/usr/bin/env bash
# Start the bridge (and serve the widget). Advanced/headless entry point; non-technical users use ../run.command.
set -euo pipefail
cd "$(dirname "$0")"
VENV="../.venv"
[ -d "$VENV" ] && source "$VENV/bin/activate" || true
[ -f .env ] && set -a && . ./.env && set +a || true
[ -f config.json ] || { echo "No config.json; copying config.example.json"; cp config.example.json config.json; }
exec python bridge.py
