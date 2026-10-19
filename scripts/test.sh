#!/usr/bin/env sh
# Offline test suite: no API keys, no paid calls, no network beyond loopback.
set -eu
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Run ./scripts/install.sh first." >&2; exit 1; }
echo "== Home Jarvis showcase"
.venv/bin/python -m pytest -q tests
echo "== Ask the Three"
(cd apps/ask-the-three && ../../.venv/bin/python -m pytest -q tests)
echo "== OTAKU Gallery"
(cd apps/otaku-gallery && ../../.venv/bin/python -m unittest discover -q)
echo "== Kiosk JavaScript syntax"
if command -v node >/dev/null 2>&1; then
  for f in kiosk/web/*.js kiosk/web/vendor/*.js; do node --check "$f"; done
  node kiosk/tests/week-calendar-en.test.cjs
else
  echo "(node not found: JavaScript checks skipped)"
fi
echo "== Public-safety audit"
.venv/bin/python scripts/public_audit.py
