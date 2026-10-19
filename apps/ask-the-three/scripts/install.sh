#!/bin/sh
# Local installation only: never installs a service or reads an existing secret.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
python_bin=${PYTHON:-python3}
"$python_bin" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
"$python_bin" -m venv .venv
.venv/bin/python -m pip install -c constraints.txt ".[dev]"
.venv/bin/ask-three-en --version
printf '%s\n' 'Installed. Run .venv/bin/ask-three-en serve (default: http://127.0.0.1:8794/).'
