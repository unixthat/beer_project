#!/usr/bin/env bash
# kill_beer.sh – helper to terminate all running BEER Battleship processes.

set -euo pipefail

# List of module entry points we may want to terminate
PATTERNS=(
    "beer.server"
    "beer.client"
    "beer.bot"
)

if [[ $(uname) == "Darwin" ]]; then
  # macOS uses BSD pkill; -f matches full command string
  for pat in "${PATTERNS[@]}"; do
    pkill -9 -f "$pat" 2>/dev/null || true
  done
else
  # GNU/Linux (assumes procps pkill)
  for pat in "${PATTERNS[@]}"; do
    pkill -9 -f "$pat" 2>/dev/null || true
  done
fi

echo "[INFO] Terminated BEER server/clients (if any were running)."
