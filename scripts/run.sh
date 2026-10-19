#!/usr/bin/env sh
# Start Ask the Three, OTAKU Gallery and the Home Jarvis kiosk showcase.
# Live mode reads NEBIUS_API_KEY from ./.env or the environment; --demo ignores keys.
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Run ./scripts/install.sh first." >&2; exit 1; }
exec .venv/bin/python scripts/run_showcase.py "$@"
