from __future__ import annotations

"""
Very simple BEER bot that fires at random coordinates until the game ends.

This rewrite keeps the public API, network handling and CLI exactly the same.
The *only* changes are inside the shooting logic:

1. **Parity hunting** – random shots are restricted to one colour of a
   checkerboard until only length-1 ships remain.
2. **Robust target mode**
   • After the second hit establishes an axis, any further hit in the same row
     (horizontal) or column (vertical) is added to the cluster, even across
     gaps.
   • A **frontier queue** stores exactly the two squares at each end of the
     cluster; once we fire at a square it is popped so we never re-fire there.
3. **Halo exclusion** – when a ship is sunk, all orthogonally-adjacent squares
   are marked as blocked so the hunt phase never wastes shots next to dead
   hulls.
4. **Clean end-of-game reset** – _awaiting_result is cleared on WIN/LOSE to
   avoid a rare hang if the last reply is not "SUNK".
"""

import argparse
import contextlib
import random
import socket
import threading
import time
from typing import Optional, Tuple

from .common import DEFAULT_KEY, FrameError, PacketType, enable_encryption, recv_pkt
from .bot_logic import BotLogic, Coord
from .client import _print_dual_grid, _is_reveal_grid

HOST = "127.0.0.1"
PORT = 5000


class BotPlayer:
    """Thin network wrapper around the strategy engine in bot_logic.BotLogic."""

    def __init__(self, verbose_level: int = 0) -> None:
        self.verbose_level = verbose_level
        self.running = True

        # Strategy engine (logic itself has no verbose flag now)
        self.logic = BotLogic()

        # Networking
        self.sock: Optional[socket.socket] = None
        self.wfile = None

        # Last shot awaiting result
        self.last_shot: Optional[Coord] = None
        self.awaiting_result = False

        # For verbose grid display
        self._last_opp_rows: list[str] | None = None
        self._last_own_rows: list[str] | None = None

    # --------------------------------------------------------------------- #
    # Utilities
    # --------------------------------------------------------------------- #
    @staticmethod
    def _coord_to_str(rc: Coord) -> str:
        r, c = rc
        return f"{chr(ord('A') + r)}{c + 1}"

    # ------------------------------------------------------------------ #
    # Network / game loop
    # ------------------------------------------------------------------ #
    def _receiver(self, sock: socket.socket) -> None:
        br = sock.makefile("rb")
        try:
            while self.running:
                try:
                    ptype, _seq, obj = recv_pkt(br)  # type: ignore[arg-type]
                except FrameError:
                    break
                except Exception as exc:
                    if self.verbose_level >= 1:
                        print("[BOT-ERR]", exc)
                    break

                if ptype != PacketType.GAME:
                    continue

                # ---------------- Grid packets ----------------
                if isinstance(obj, dict) and obj.get("type") == "grid":
                    rows = obj["rows"]
                    if _is_reveal_grid(rows):
                        self._last_own_rows = rows
                    else:
                        self._last_opp_rows = rows
                        if self.verbose_level >= 2 and self._last_own_rows:
                            _print_dual_grid(self._last_opp_rows, self._last_own_rows)
                    continue

                msg = obj.get("msg", "") if isinstance(obj, dict) else ""
                upper = msg.upper()

                # Auto-accept default placement
                if msg.startswith("INFO Manual placement"):
                    if self.wfile:
                        self.wfile.write("n\n"), self.wfile.flush()
                    continue

                # Handle outcome of the previous shot
                if self.awaiting_result and self.last_shot:
                    coord = self.last_shot
                    if upper.startswith("HIT"):
                        if self.verbose_level == 1:
                            print(msg)
                        self.logic.register_result("HIT", coord)
                        self.awaiting_result = False
                    elif upper.startswith("MISS") or "MISS" in upper:
                        if self.verbose_level == 1:
                            print(msg)
                        self.logic.register_result("MISS", coord)
                        self.awaiting_result = False
                    elif upper.startswith("SUNK") or "SUNK" in upper:
                        if self.verbose_level == 1:
                            print(msg)
                        self.logic.register_result("SUNK", coord)
                        self.awaiting_result = False
                    elif "ERR" in upper or "INVALID" in upper:
                        self.awaiting_result = False

                # Extra SUNK line outside awaiting state (our partner sunk by previous HIT)
                if upper.startswith("SUNK"):
                    if self.verbose_level == 1:
                        print(msg)
                    self.logic.register_result("SUNK", (-1, -1))
                    continue

                # Decide to shoot
                if "YOUR TURN" in upper:
                    r, c = self.logic.choose_shot()
                    coord = self._coord_to_str((r, c))
                    if self.wfile:
                        self.wfile.write(f"FIRE {coord}\n"), self.wfile.flush()
                    self.logic.shots_taken.add((r, c))
                    self.last_shot = (r, c)
                    self.awaiting_result = True
                    if self.verbose_level == 1:
                        print(f"SHOT {coord}")
                    continue

                # End-of-game human-readable messages are printed as-is in high verbose
                if upper.startswith(("WIN", "LOSE", "INFO")) and self.verbose_level >= 2:
                    print(msg)

                if upper.startswith(("WIN", "LOSE")):
                    self.awaiting_result = False
                    self.running = False
                    break
        finally:
            self.running = False

    # ------------------------------------------------------------------ #
    # Runner
    # ------------------------------------------------------------------ #
    def run(self, host: str, port: int) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            self.sock = s
            self.wfile = s.makefile("w")

            recv_thr = threading.Thread(
                target=self._receiver, args=(s,), daemon=True
            )
            recv_thr.start()

            try:
                while self.running and recv_thr.is_alive():
                    time.sleep(0.1)
            except KeyboardInterrupt:
                if self.verbose_level >= 1:
                    print("\n[BOT] Interrupted – shutting down…")
                self.running = False
                with contextlib.suppress(Exception):
                    if self.wfile:
                        self.wfile.write("QUIT\n"), self.wfile.flush()
                time.sleep(0.2)


# ------------------------------------------------------------------ #
# CLI entry-point
# ------------------------------------------------------------------ #
def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Very simple BEER auto-play bot")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--secure", nargs="?", const="default")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v: log shots, -vv: full verbose with boards")
    args = parser.parse_args()

    if args.secure is not None:
        key = DEFAULT_KEY if args.secure == "default" else bytes.fromhex(args.secure)
        enable_encryption(key)
        print("[BOT] Encryption enabled")

    BotPlayer(verbose_level=args.verbose).run(args.host, args.port)


if __name__ == "__main__":
    main()
