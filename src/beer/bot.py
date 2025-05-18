"""Automated Battleship bot (CLI entry-point).

This implementation intentionally *reuses* as much rendering / packet handling
logic from the interactive client so the two stay in sync.  The only
behavioural difference is that the bot automatically chooses and fires a shot
at every turn using `beer.bot_logic.BotLogic` (or the simpler parity bot if
`BEER_SIMPLE_BOT=1` is exported).
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time
from typing import Callable, Dict, Optional

from . import config as _cfg
from .bot_logic import BotLogic  # selection logic obeys BEER_SIMPLE_BOT
from .common import (
    FrameError,
    IncompleteError,
    PacketType,
    recv_pkt,
    enable_encryption,
    DEFAULT_KEY,
)

# Re-use helper renderers from the interactive client
from .client import _print_two_grids, _is_reveal_grid

HOST = _cfg.DEFAULT_HOST
PORT = _cfg.DEFAULT_PORT

# ------------- module-level logger -------------
logging.basicConfig(
    level=logging.DEBUG if _cfg.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------- internal utils -----------------


class _BotState:
    """Lightweight container tracking the bot's own game state."""

    def __init__(self, logic: BotLogic, wfile):
        self.logic = logic
        self.wfile = wfile  # TextIO – writes plain protocol lines
        self.awaiting_result = False
        self.last_shot: Optional[str] = None  # coordinate string eg "B7"

    # --- helpers ------------------------------------------------------
    @staticmethod
    def _coord_to_str(rc):
        r, c = rc
        return f"{chr(ord('A') + r)}{c + 1}"

    def fire(self):
        """Choose next coordinate, send FIRE command, mark awaiting_result."""
        rc = self.logic.choose_shot()
        coord_txt = self._coord_to_str(rc)
        try:
            self.wfile.write(f"FIRE {coord_txt}\n")
            self.wfile.flush()
            # Emit a simple line for tests / log grepping
            print(f"SHOT {coord_txt}", flush=True)
            logger.debug("Fired at %s", coord_txt)
            self.awaiting_result = True
            self.last_shot = coord_txt
            # Respect configured bot loop delay
            time.sleep(_cfg.BOT_LOOP_DELAY)
        except Exception as exc:
            logger.error("Failed to write FIRE command: %s", exc)

    def handle_result_line(self, msg: str):
        """Update BotLogic with the outcome of its previous shot."""
        if not self.awaiting_result or not self.last_shot:
            return
        outcome = None
        if "HIT" in msg:
            outcome = "HIT"
        elif "MISS" in msg:
            outcome = "MISS"
        elif "SUNK" in msg:
            outcome = "HIT"  # treat SUNK as HIT for logic purposes
        if outcome:
            rc = self._str_to_coord(self.last_shot)
            self.logic.register_result(outcome, rc)
            self.awaiting_result = False

    @staticmethod
    def _str_to_coord(coord: str):
        row = ord(coord[0]) - ord("A")
        col = int(coord[1:]) - 1
        return (row, col)


# ---------------- receiver thread -----------------


class BotReceiver(threading.Thread):
    """Background thread that listens to framed packets and updates the bot state.

    The previous implementation used one large nested function with several
    `def` blocks inside – this class-based refactor flattens the control-flow
    and exposes every handler as a *method* instead.  This is considerably
    easier to read, understand and unit-test.
    """

    def __init__(self, sock: socket.socket, state: _BotState, stop_evt: threading.Event, verbose: int):
        super().__init__(daemon=True)
        self._sock = sock
        self._state = state
        self._stop_evt = stop_evt
        self._verbose = verbose
        # Determine this bot's role: will be set on START raw message
        self._my_index: Optional[int] = None

        # Convenience wrappers
        self._br = sock.makefile("rb")

        # Board caches for pretty printing
        self._last_own: Optional[list[str]] = None
        self._last_opp: Optional[list[str]] = None

        # Map structured GAME → handler method
        self._handlers: Dict[str, Callable[[dict], None]] = {
            "spec_grid": self._on_spec_grid,
            "grid": self._on_grid,
            "chat": self._on_chat,  # rarely used (raw chat frame)
            "end": self._on_end,
        }

    # ---------------------------------------------------------------------
    # Helper handler methods – each consumes a *structured* GAME payload.
    # ---------------------------------------------------------------------

    def _on_spec_grid(self, obj: dict) -> None:
        if self._verbose < 2 or "spec_grid" in _cfg.QUIET_CATEGORIES:
            return
        _print_two_grids(
            obj.get("rows_p1", []),
            obj.get("rows_p2", []),
            header_left="Player 1",
            header_right="Player 2",
        )

    def _on_grid(self, obj: dict) -> None:
        rows = obj["rows"]
        if _is_reveal_grid(rows):
            self._last_own = rows
            return
        self._last_opp = rows
        if self._verbose >= 0 and self._last_own and "grid" not in _cfg.QUIET_CATEGORIES:
            _print_two_grids(self._last_opp, self._last_own, header_left="Opp Fleet", header_right="Your Fleet")

    def _on_chat(self, obj: dict) -> None:
        if "chat" in _cfg.QUIET_CATEGORIES or self._verbose < 0:
            return
        print(f"[CHAT] {obj.get('name')}: {obj.get('msg')}")

    def _on_end(self, obj: dict) -> None:
        winner = obj.get("winner")
        shots = obj.get("shots")
        # Print result from this bot's perspective
        if getattr(self, "_my_index", None) == winner:
            print("WIN")
        else:
            print("LOSE")
        print(f"Game finished in {shots} shots")
        self._stop_evt.set()

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def run(self) -> None:  # noqa: C901 – complex but contained
        try:
            while not self._stop_evt.is_set():
                try:
                    ptype, _seq, obj = recv_pkt(self._br)  # type: ignore[arg-type]
                except IncompleteError:
                    self._stop_evt.set()
                    break
                except FrameError as exc:
                    logger.error("Frame error encountered: %s", exc)
                    self._stop_evt.set()
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Unexpected exception in recv loop: %s", exc)
                    self._stop_evt.set()
                    break

                # Structured CHAT frames
                if ptype == PacketType.CHAT and isinstance(obj, dict):
                    self._on_chat(obj)
                    continue

                # Ignore non-GAME payloads (keep-alive etc.)
                if ptype != PacketType.GAME or not isinstance(obj, dict):
                    continue

                # Structured GAME sub-type
                kind = obj.get("type")
                if kind in self._handlers:
                    self._handlers[kind](obj)
                    continue

                # Legacy raw message fallback
                msg: str = obj.get("msg", "")
                if not msg:
                    continue

                self._handle_raw_message(msg)
        finally:  # Always clean up
            self._stop_evt.set()
            logger.info("Receiver stopped, cleaning up resources.")

    # ------------------------------------------------------------------
    # Raw message fall-through helpers
    # ------------------------------------------------------------------

    def _handle_raw_message(self, msg: str) -> None:
        """Deal with old-style string messages – bots depend on these."""
        # Capture this bot's player index from START message
        if msg.startswith("START you"):
            self._my_index = 1
            return
        if msg.startswith("START opp"):
            self._my_index = 2
            return
        # Human-readable echo (respect verbosity)
        if self._verbose >= 0 and (msg.startswith("YOU ") or msg.startswith("OPPONENT ")):
            print(msg)
        elif self._verbose >= 1 and "raw" not in _cfg.QUIET_CATEGORIES:
            print(msg)

        # Auto responses
        if msg.startswith("INFO Manual placement?"):
            self._state.wfile.write("n\n")
            self._state.wfile.flush()
            return
        if msg.startswith("INFO Your turn"):
            self._state.fire()
            return
        if msg.startswith("YOU "):
            self._state.handle_result_line(msg)


# -------------------------- main ----------------------------


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Automated BEER Battleship bot")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for deterministic play")
    parser.add_argument(
        "--secure", nargs="?", const="default", help="Enable AES-CTR encryption optionally with hex key"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (stackable)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress all stdout except final result")
    args = parser.parse_args()

    if args.debug:
        os.environ["BEER_DEBUG"] = "1"

    # Effective verbosity: quiet => -1, else count of -v (0/1/2)
    verbose = -1 if args.quiet else args.verbose

    if args.secure is not None:
        key = DEFAULT_KEY if args.secure == "default" else bytes.fromhex(args.secure)
        enable_encryption(key)
        if verbose >= 0:
            print("[INFO] Encryption enabled in bot")

    logic = BotLogic(seed=args.seed)

    # keep playing until user hits Ctrl-C
    while True:
        try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((args.host, args.port))
        wfile = s.makefile("w")
        state = _BotState(logic, wfile)

        stop_evt = threading.Event()
        receiver = BotReceiver(s, state, stop_evt, verbose)
        receiver.start()

                # wait for game to finish (stop_evt set in _on_end)
            while not stop_evt.is_set():
                receiver.join(timeout=0.5)
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user – quitting")
            break
        # otherwise, loop will reconnect and re-enter the queue


if __name__ == "__main__":  # pragma: no cover
    main()
