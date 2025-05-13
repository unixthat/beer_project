#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# start_venv_macos.sh – helper for macOS developers
# -----------------------------------------------------------------------------
# Creates a Python virtual environment in the repository (./venv by default)
# and activates it.  If the venv already exists, it is reused.
#
# This script is macOS-friendly: it tries Homebrew's Python if the requested
# executable is not on PATH.
#
# Usage: ./start_venv_macos.sh [venv_dir] [python_executable]
#        venv_dir           defaults to "venv" in the repo root
#        python_executable  defaults to the first 'python3' found on PATH
#
# After running, your shell will have the venv activated.  Type `deactivate`
# to exit.
# -----------------------------------------------------------------------------
set -euo pipefail

# Move to the repository root (directory containing this script)
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

VENV_DIR="${1:-venv}"
# Prefer Homebrew Python 3.11 unless caller provided an explicit interpreter
if [ -n "${2-}" ]; then
  PYTHON_BIN="$2"
else
  # Try to locate Homebrew's python@3.11 first (Apple Silicon and Intel prefixes)
  if command -v "/opt/homebrew/opt/python@3.11/bin/python3" &>/dev/null; then
    PYTHON_BIN="/opt/homebrew/opt/python@3.11/bin/python3"
  elif command -v "/usr/local/opt/python@3.11/bin/python3" &>/dev/null; then
    PYTHON_BIN="/usr/local/opt/python@3.11/bin/python3"
  elif command -v brew &>/dev/null && BREW_PY=$(brew --prefix python@3.11 2>/dev/null)/bin/python3 && [ -x "$BREW_PY" ]; then
    PYTHON_BIN="$BREW_PY"
  else
    PYTHON_BIN="python3"
  fi
fi

# Locate a usable Python 3 interpreter -------------------------------------------------
if ! command -v "$PYTHON_BIN" &>/dev/null; then
  # On Apple Silicon installs, Homebrew typically lives under /opt/homebrew
  # Fallback to the generic Homebrew python3 if available
  if command -v /opt/homebrew/bin/python3 &>/dev/null; then
    PYTHON_BIN="/opt/homebrew/bin/python3"
  else
    echo "Error: Could not find '$PYTHON_BIN'. Install Python 3 (e.g. 'brew install python@3.11') or pass an explicit path." >&2
    exit 1
  fi
fi

echo "[INFO] Using Python interpreter: $PYTHON_BIN (version $($PYTHON_BIN --version 2>&1))"

# Create the virtual environment if needed ----------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  echo "[INFO] Creating new virtual environment in ./$VENV_DIR …"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Activate the venv ---------------------------------------------------------------------
# shellcheck disable=SC1090  # path constructed above
source "$VENV_DIR/bin/activate"

echo "[INFO] Virtual environment activated.  Python: $(python --version 2>&1)"

# Upgrade pip and install dev dependencies (quietly) -------------------------------------
python -m pip install --quiet --upgrade pip

if [ -f "dev-requirements.txt" ]; then
  echo "[INFO] Installing dev dependencies …"
  pip install --quiet -r dev-requirements.txt
fi

echo "[INFO] Done.  To deactivate, type 'deactivate'."
