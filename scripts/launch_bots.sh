#!/usr/bin/env bash
# launch_bots.sh – start two autonomous BEER bots that attach to an already-running beer-server.
# Usage: ./launch_bots.sh [host] [port]
# Defaults: host=127.0.0.1  port=5000

set -euo pipefail
HOST=${1:-127.0.0.1}
PORT=${2:-5000}

# Start first bot
beer-bot --host "$HOST" --port "$PORT" &
BOT1=$!

echo "[INFO] beer-bot #1 started (PID $BOT1)"

# Start second bot
beer-bot --host "$HOST" --port "$PORT" &
BOT2=$!

echo "[INFO] beer-bot #2 started (PID $BOT2)"

echo "[INFO] Both bots are now connected to $HOST:$PORT."

echo "Press Ctrl+C to terminate both bots."

# Wait until user interrupts
trap "kill $BOT1 $BOT2 2>/dev/null || true" INT TERM
wait
