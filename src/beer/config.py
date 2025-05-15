"""Central configuration for runtime-tunable parameters.

All constants can be overridden via environment variables so that the
production game server/bot runs at full speed by default, while the
automated test-suite can slow specific components down if necessary.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Test Log Directory (used by test helpers)
# ---------------------------------------------------------------------------
# Points to <project_root>/tests/logs/
TEST_LOG_DIR = Path(__file__).resolve().parent.parent / "tests" / "logs"

# ---------------------------------------------------------------------------
# Bot timing
# ---------------------------------------------------------------------------
# Delay (in seconds) between iterations of the main bot sender loop.
# Defaults to **0.0** (no delay, maximum speed).  Integration tests can set
#   export BEER_BOT_DELAY=0.05
# to make log interleaving more deterministic.
BOT_LOOP_DELAY: float = float(os.getenv("BEER_BOT_DELAY", "0"))

# ---------------------------------------------------------------------------
# Bot algorithm selection
# ---------------------------------------------------------------------------
# When True the client/bot will use the simplistic parity-only strategy.
# Default = False (use advanced axis-targeting AI).  Can be overridden via
#   export BEER_SIMPLE_BOT=1
# or the `--simple` CLI flag on `beer.bot` which sets this at runtime before
# spawning the strategy engine.

SIMPLE_BOT: bool = os.getenv("BEER_SIMPLE_BOT", "0") == "1"

# ---------------------------------------------------------------------------
# Server: per-turn defender poll delay (seconds)
# ---------------------------------------------------------------------------
# During each turn the server briefly polls the *non-active* player's socket to
# detect out-of-turn traffic or disconnects.  The original hard-coded value
# of 0.1 s adds noticeable latency (≈ 9 s for a 90-shot game).  Make it
# configurable and default it to **0.0** for maximum throughput.  Integration
# tests can bump it to e.g. 0.02 if they rely on deterministic interleaving.

SERVER_POLL_DELAY: float = float(os.getenv("BEER_SERVER_POLL_DELAY", "0"))

# ---------------------------------------------------------------------------
# Network defaults (host, port)
# ---------------------------------------------------------------------------

DEFAULT_HOST: str = os.getenv("BEER_HOST", "127.0.0.1")
DEFAULT_PORT: int = int(os.getenv("BEER_PORT", "5000"))

# ---------------------------------------------------------------------------
# Gameplay timing
# ---------------------------------------------------------------------------
# Per-turn timeout for a player to issue a FIRE command (seconds)

TURN_TIMEOUT: int = int(os.getenv("BEER_TURN_TIMEOUT", "180"))  # default 3 min

# Timeout waiting for manual ship placement input (seconds)

PLACEMENT_TIMEOUT: int = int(os.getenv("BEER_PLACE_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Cryptography (optional AES key)
# ---------------------------------------------------------------------------

DEFAULT_KEY_HEX: str = os.getenv("BEER_KEY", "00112233445566778899AABBCCDDEEFF")
DEFAULT_KEY: bytes = bytes.fromhex(DEFAULT_KEY_HEX)

# ---------------------------------------------------------------------------
# Game constants (board + ships)
# ---------------------------------------------------------------------------

BOARD_SIZE: int = int(os.getenv("BEER_BOARD_SIZE", "10"))

SHIPS = [
    ("Carrier", 5),
    ("Battleship", 4),
    ("Cruiser", 3),
    ("Submarine", 3),
    ("Destroyer", 2),
]

SHIP_LETTERS = {
    "Carrier": "A",  # Aircraft carrier (avoid clash with Cruiser)
    "Battleship": "B",
    "Cruiser": "C",
    "Submarine": "S",
    "Destroyer": "D",
}

# ---------------------------------------------------------------------------
# Debug / logging
# ---------------------------------------------------------------------------

DEBUG: bool = os.getenv("BEER_DEBUG", "0") == "1"

# Comma-separated packet categories that the client/bot should *not* print when
# DEBUG is disabled.  Can be overridden by `BEER_QUIET="chat,spec_grid"`.

QUIET_CATEGORIES: list[str] = os.getenv("BEER_QUIET", "").split(",") if os.getenv("BEER_QUIET") else []

# Heartbeat interval for server-client communication (seconds)
HEARTBEAT_INTERVAL: float = float(os.getenv("BEER_HEARTBEAT_INTERVAL", "1"))  # default 1 second
