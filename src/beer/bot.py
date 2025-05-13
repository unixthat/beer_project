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
import os
from typing import Optional, Tuple
import numpy as np

from .common import DEFAULT_KEY, FrameError, PacketType, enable_encryption, recv_pkt
from .bot_logic import BotLogic, Coord
# Optional RL policy – imported lazily to avoid heavy deps during test runs
try:
    from .ppo_bot import next_shot as ppo_next_shot, load as ppo_load
except Exception:  # pragma: no cover – SB3 stack likely missing in CI
    ppo_next_shot = None  # type: ignore
    ppo_load = None  # type: ignore
from .client import _print_dual_grid, _is_reveal_grid

HOST = "127.0.0.1"
PORT = 5000


class BotPlayer:
    """Thin network wrapper around the strategy engine in bot_logic.BotLogic."""

    def __init__(self, verbose_level: int = 0, *, ppo_model: str | None = None) -> None:
        self.verbose_level = verbose_level
        self.running = True

        # ---------------- Strategy engines ----------------
        # 1. Classic deterministic heuristic (default for unit-tests)
        self.logic = BotLogic()
        # 2. Optional PPO – activated when *ppo_model* is supplied and sb3 stack available.
        self._ppo_model_path: str | None = ppo_model or os.getenv("BEER_PPO_MODEL")
        self._ppo_ready = False
        if self._ppo_model_path:
            if ppo_load is None:
                raise RuntimeError(
                    "PPO model requested but stable-baselines3 / gym not installed; "
                    "run `pip install stable-baselines3 gymnasium gym-battleship sb3-contrib`"
                )
            try:
                ppo_load(self._ppo_model_path, masked=True)
                self._ppo_ready = True
            except Exception as exc:
                raise RuntimeError(f"Failed to load PPO model {self._ppo_model_path}: {exc}") from exc

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
                    if self._ppo_ready and ppo_next_shot is not None:
                        # Construct 100-element fired mask (row-major)
                        obs = np.zeros((2, 10, 10), dtype=np.float32)
                        for (r, c) in self.logic.shots_taken:
                            obs[1, r, c] = 1.0
                        r, c = ppo_next_shot(obs)
                        # Avoid accidental refire into an already-shot cell
                        # (should be prevented by action mask but be safe)
                        if (r, c) in self.logic.shots_taken:
                            # fall back to heuristic
                            r, c = self.logic.choose_shot()
                    else:
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
    parser.add_argument("--ppo-model", help="Path to a Stable-Baselines3 PPO model to drive the bot instead of heuristics")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v: log shots, -vv: full verbose with boards")
    args = parser.parse_args()

    if args.secure is not None:
        key = DEFAULT_KEY if args.secure == "default" else bytes.fromhex(args.secure)
        enable_encryption(key)
        print("[BOT] Encryption enabled")

    BotPlayer(verbose_level=args.verbose, ppo_model=args.ppo_model).run(args.host, args.port)


if __name__ == "__main__":
    main()
