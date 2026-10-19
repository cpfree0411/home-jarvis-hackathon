#!/usr/bin/env sh
# Create one virtual environment for the whole showcase and install both
# English apps into it (editable, so the source you read is the code that runs).
# Needs Python 3.11+ with venv and network access to PyPI. Installs no service.
set -eu
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required")'
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade --quiet pip
.venv/bin/python -m pip install --quiet -c apps/ask-the-three/constraints.txt \
  -e './apps/ask-the-three[dev]' -e ./apps/otaku-gallery
echo "Installed. Start with: ./scripts/run.sh   (demo: ./scripts/run.sh --demo)"
