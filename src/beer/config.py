"""Central configuration for runtime-tunable parameters.

All constants can be overridden via environment variables so that the
production game server/bot runs at full speed by default, while the
automated test-suite can slow specific components down if necessary.
"""

from __future__ import annotations

import os
from pathlib import Path

# ===========================================================================
# Test Log Directory
# ===========================================================================
# Directory where bot and server logs are stored during automated tests.
# Path: <project_root>/tests/logs/
TEST_LOG_DIR = Path(__file__).resolve().parent.parent / "tests" / "logs"


# ===========================================================================
# Bot Algorithm Selection
# ===========================================================================
# BEER_SIMPLE_BOT: If "1", the bot uses a simplistic parity-only targeting strategy.
#   Defaults to "0" (use advanced axis-targeting AI).
#   Can also be set via the `--simple` CLI flag on `beer.bot`.
#   Example: export BEER_SIMPLE_BOT=1
SIMPLE_BOT: bool = os.getenv("BEER_SIMPLE_BOT", "0") == "1"


# ===========================================================================
# Server Timing Controls
# ===========================================================================
# BEER_SERVER_POLL_DELAY: Delay (in seconds) for the server polling the non-active player's socket.
#   This is used to detect out-of-turn traffic or disconnects.
#   Defaults to 0.0 (maximum throughput).
#   A small value (e.g., 0.02) can make test log interleaving more deterministic.
#   Example: export BEER_SERVER_POLL_DELAY=0.02
SERVER_POLL_DELAY: float = float(os.getenv("BEER_SERVER_POLL_DELAY", "0"))


# ===========================================================================
# Network Defaults
# ===========================================================================
# BEER_HOST: Default host address for the server to bind to and clients to connect to.
#   Defaults to "127.0.0.1".
#   Example: export BEER_HOST=0.0.0.0
DEFAULT_HOST: str = os.getenv("BEER_HOST", "127.0.0.1")

# BEER_PORT: Default port for the server to listen on and clients to connect to.
#   Defaults to 61337
#   Note: Port 5000 is used by another process on macOS, using it may cause unexpected behaviour.
#   Example: export BEER_PORT=5001
DEFAULT_PORT: int = int(os.getenv("BEER_PORT", "61337"))


# ===========================================================================
# Unified Action & Reconnect Timeout
# ===========================================================================
# BEER_TIMEOUT: seconds for both "your turn" inactivity and reconnect wait.
# Defaults to 60 seconds. Example: export BEER_TIMEOUT=30
TIMEOUT: float = float(os.getenv("BEER_TIMEOUT", "60"))

# ===========================================================================
# Default Ports
# ===========================================================================
# BEER_TEST_PORT: port to use in automated tests (default 61338)
TEST_PORT: int = int(os.getenv("BEER_TEST_PORT", "61338"))


# ===========================================================================
# Game Constants
# ===========================================================================
# BEER_BOARD_SIZE: Defines the width and height of the game board.
#   Defaults to 10 (for a 10x10 grid).
#   Example: export BEER_BOARD_SIZE=8
BOARD_SIZE: int = int(os.getenv("BEER_BOARD_SIZE", "10"))

# Standard ship roster: list of (name, size) tuples. Not typically overridden by env vars.
SHIPS = [
    ("Carrier", 5),
    ("Battleship", 4),
    ("Cruiser", 3),
    ("Submarine", 3),
    ("Destroyer", 2),
]

# Unique single-letter representations for each ship on the board.
SHIP_LETTERS = {
    "Carrier": "A",  # "A" for Aircraft carrier to avoid clash with Cruiser's "C"
    "Battleship": "B",
    "Cruiser": "C",
    "Submarine": "S",
    "Destroyer": "D",
}


# ===========================================================================
# Debugging and Logging
# ===========================================================================
# BEER_DEBUG: If "1", enables detailed debug logging across modules.
#   Defaults to "0" (disabled).
#   Example: export BEER_DEBUG=1
DEBUG: bool = os.getenv("BEER_DEBUG", "0") == "1"

# BEER_QUIET: Comma-separated list of packet categories that the client/bot should *not* print
#   when BEER_DEBUG is disabled. Effective for reducing log noise.
#   Defaults to an empty list (all categories printed).
#   Example: export BEER_QUIET="chat,spec_grid"
QUIET_CATEGORIES: list[str] = os.getenv("BEER_QUIET", "").split(",") if os.getenv("BEER_QUIET") else []

# ===========================================================================
# Cryptography Defaults
# ===========================================================================
# BEER_KEY: AES encryption key as a hex string.
# Defaults to "00112233445566778899AABBCCDDEEFF".
DEFAULT_KEY_HEX: str = os.getenv("BEER_KEY", "00112233445566778899AABBCCDDEEFF")
DEFAULT_KEY: bytes = bytes.fromhex(DEFAULT_KEY_HEX)
