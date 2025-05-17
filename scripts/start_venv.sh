#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# start_venv.sh – helper for WSL/Ubuntu developers
# -----------------------------------------------------------------------------
# Creates a Python virtual environment in the repo (./venv) if absent and
# activates it.  Subsequent shells can simply `source venv/bin/activate`.
#
# Usage: ./start_venv.sh [python_executable]
#        python_executable defaults to the first 'python3' on PATH.
# -----------------------------------------------------------------------------
set -euo pipefail

# Change to the directory where this script resides (repo root)
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

PYTHON="${1:-python3}"

# Ensure Python is present
if ! command -v "$PYTHON" &>/dev/null; then
  echo "Error: '$PYTHON' not found in PATH. Install Python 3.x or specify a path." >&2
  exit 1
fi

# Create venv if it doesn't exist (we use ./venv to match .gitignore)
if [ ! -d "venv" ]; then
  echo "[INFO] Creating new virtual environment in ./venv using $PYTHON…"
  "$PYTHON" -m venv venv
fi

# Activate it
# shellcheck disable=SC1091  # runtime path checked above
source "venv/bin/activate"

echo "[INFO] Virtual environment activated.  Python: $(python --version)"

# Upgrade pip and install dev deps if the file exists
if [ -f "dev-requirements.txt" ]; then
  echo "[INFO] Installing dev dependencies…"
  pip install --quiet --upgrade pip
  pip install --quiet -r dev-requirements.txt
fi

echo "[INFO] Done.  To deactivate, type 'deactivate'."
