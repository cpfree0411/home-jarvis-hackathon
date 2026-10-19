#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
python_bin=${PYTHON:-.venv/bin/python}
"$python_bin" -m compileall -q ask_three_en scripts tests
"$python_bin" -m pytest -q
"$python_bin" scripts/public_audit.py
if command -v node >/dev/null 2>&1; then
    node --check ask_three_en/web/app.js
fi
