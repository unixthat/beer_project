"""CLI client wrapper in the package version."""

from __future__ import annotations

import argparse
import socket
import threading
from io import BufferedReader, BufferedWriter
from typing import TextIO, Optional, Callable, Dict
import os
import logging
import time
from pathlib import Path

from .common import (
    PacketType,
    FrameError,
    IncompleteError,
    recv_pkt,
    enable_encryption,
    DEFAULT_KEY,
)
from .battleship import SHIP_LETTERS
from . import config as _cfg

HOST = _cfg.DEFAULT_HOST
PORT = _cfg.DEFAULT_PORT

# Logging setup respects global DEBUG flag
logging.basicConfig(level=logging.DEBUG if _cfg.DEBUG else logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ------------------- PID-token persistence -------------------
TOKEN_FILE = Path.home() / ".beer_pidtoken"
if TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text().strip()
else:
    TOKEN = f"PID{os.getpid()}"
    TOKEN_FILE.write_text(TOKEN)

# ---------------------------- receiver -----------------------------


def _print_grid(rows: list[str]) -> None:
    print("\n[Board]")
    columns = len(rows[0].split())
    header = "   " + " ".join(f"{i:>2}" for i in range(1, columns + 1))
    print(header)
    for idx, row in enumerate(rows):
        label = chr(ord("A") + idx)
        cells = row.split()
        formatted = " ".join(f"{c:>2}" for c in cells)
        print(f"{label:2} {formatted}")


# ------------------------------------------------------------
# Enhanced dual-board renderer
# ------------------------------------------------------------


_SHIP_CHARS = set(SHIP_LETTERS.values())


def _is_reveal_grid(rows: list[str]) -> bool:
    """Return True if *rows* contain ship letters, i.e. own fleet view."""
    for row in rows:
        for cell in row.split():
            if cell in _SHIP_CHARS:
                return True
    return False


def _print_two_grids(
    left_rows: list[str],
    right_rows: list[str],
    *,
    header_left: str,
    header_right: str,
) -> None:
    """Helper to print two 10×10 boards side-by-side with custom headers."""

    if not left_rows or not right_rows:
        return

    columns = len(left_rows[0].split())
    numeric_header = "   " + " ".join(f"{i:>2}" for i in range(1, columns + 1))

    board_width = len(numeric_header)
    left_header_text = f"[{header_left}]"
    right_header_text = f"[{header_right}]"

    left_header = left_header_text.center(board_width)
    right_header = right_header_text.center(board_width)

    # Print centred headers without the previous pipe separator
    print(f"\n{left_header}   {right_header}")

    # Print numeric column labels (no pipe)
    print(f"{numeric_header}   {numeric_header}")

    for idx in range(len(left_rows)):
        label = chr(ord("A") + idx)
        left_cells = left_rows[idx].split()
        right_cells = right_rows[idx].split()
        left = " ".join(f"{c:>2}" for c in left_cells)
        right = " ".join(f"{c:>2}" for c in right_cells)
        print(f"{label:2} {left}   {label:2} {right}")


# ------------------------------------------------------------
# Receiver
# ------------------------------------------------------------


def _prompt() -> None:
    """Display the user-input prompt."""
    print(">> ", end="", flush=True)


def _recv_loop(sock: socket.socket, stop_evt: threading.Event, verbose: int) -> None:  # pragma: no cover
    """Continuously print messages from the server (framed packets only)."""
    br = sock.makefile("rb")  # buffered reader

    last_opp: Optional[list[str]] = None
    last_own: Optional[list[str]] = None

    # ---------------- Handler helpers ----------------

    def h_spec_grid(obj: dict) -> None:
        if "spec_grid" in _cfg.QUIET_CATEGORIES:
            return
        rows_p1 = obj.get("rows_p1", [])
        rows_p2 = obj.get("rows_p2", [])
        _print_two_grids(rows_p1, rows_p2, header_left="Player 1", header_right="Player 2")

    def h_grid(obj: dict) -> None:
        rows = obj["rows"]
        if _is_reveal_grid(rows):
            # store own rows for later dual render
            nonlocal last_own
            last_own = rows
        else:
            nonlocal last_opp
            last_opp = rows
            # always print dual-board at default verbosity
            if verbose >= 0 and last_own and "grid" not in _cfg.QUIET_CATEGORIES:
                _print_two_grids(last_opp, last_own, header_left="Opponent Fleet", header_right="Your Fleet")

    def h_shot(obj: dict) -> None:
        if "shot" in _cfg.QUIET_CATEGORIES:
            return
        attacker = obj.get("player")
        coord = obj.get("coord")
        result = obj.get("result")
        sunk = obj.get("sunk") or ""
        if verbose >= 0:
            line = f"SHOT {coord} (P{attacker} {result})"
            if sunk:
                line += f" SUNK {sunk}"
            print(line)

    def h_chat(obj: dict) -> None:
        if "chat" in _cfg.QUIET_CATEGORIES:
            return
        name = obj.get("name")
        msg_txt = obj.get("msg")
        if verbose >= 0:
            print(f"[CHAT] {name}: {msg_txt}")

    def h_end(obj: dict) -> None:
        if "end" in _cfg.QUIET_CATEGORIES:
            return
        winner = obj.get("winner")
        shots = obj.get("shots")
        if winner == 1:
            print(f"YOU WON with {shots} shots")
        else:
            print(f"YOU LOST – opponent won with {shots} shots")
        # Clean up PID-token cache after match conclusion
        try:
            TOKEN_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    handlers: Dict[str, Callable[[dict], None]] = {
        "spec_grid": h_spec_grid,
        "grid": h_grid,
        "shot": h_shot,
        "chat": h_chat,
        "end": h_end,
    }

    try:
        while True:
            try:
                ptype, seq, obj = recv_pkt(br)  # type: ignore[arg-type]
            except IncompleteError:
                # Stream closed cleanly – exit receiver loop without warning.
                stop_evt.set()
                break
            except FrameError as exc:
                if verbose >= 0:
                    print(f"[WARN] Frame error: {exc}.")
                stop_evt.set()
                break
            except Exception:
                # Socket closed or unreadable – terminate receiver thread.
                stop_evt.set()
                break

            if ptype == PacketType.GAME and isinstance(obj, dict):
                if _cfg.DEBUG:
                    logger.debug("Recv packet %s", obj)
                p = obj.get("type")
                if p in handlers:
                    handlers[p](obj)
                else:
                    # Fallback: server text (START/INFO/ERR) and raw frames
                    msg = obj.get("msg", "")
                    if not msg:
                        continue
                    # INFO and ERR messages always shown
                    if msg.startswith("INFO ") or msg.startswith("ERR ") or msg.startswith("[INFO] "):
                        print(f"\r{msg}")
                    # Raw/unrecognized frames at verbose>=1
                    elif verbose >= 1 and "raw" not in _cfg.QUIET_CATEGORIES:
                        print(obj)
            elif ptype == PacketType.CHAT and isinstance(obj, dict):
                handlers["chat"](obj)
            else:
                if verbose >= 1 and "raw" not in _cfg.QUIET_CATEGORIES:
                    print(obj)
    except Exception as exc:  # noqa: BLE001
        if verbose >= 0:
            print(f"[ERROR] Receiver thread crashed: {exc!r}")
    finally:
        stop_evt.set()


# ----------------------------- main -------------------------------


def main() -> None:    # pragma: no cover – CLI entry
    """Interactive CLI client."""

    parser = argparse.ArgumentParser(description="BEER CLI client")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--secure", nargs="?", const="default", help="Enable AES-CTR encryption optionally with hex key"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (stackable)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress most output",
    )
    args = parser.parse_args()

    # Set the BEER_DEBUG environment variable based on the --debug flag
    if args.debug:
        os.environ["BEER_DEBUG"] = "1"

    # Determine effective verbosity
    global _VERBOSE_LEVEL  # noqa: PLW0603
    _VERBOSE_LEVEL = -1 if args.quiet else args.verbose

    if args.secure is not None:
        key = DEFAULT_KEY if args.secure == "default" else bytes.fromhex(args.secure)
        enable_encryption(key)
        print("[INFO] Encryption enabled in client")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        _client(s, args)


# Internal client loop invoked from main
def _client(s, args):
    addr = (args.host, args.port)
    # Retry loop: once-per-second until connected or interrupted
    while True:
        try:
            s.connect(addr)
            # Send PID-token handshake immediately
            try:
                s.sendall(f"TOKEN {TOKEN}\n".encode())
            except Exception:
                pass
            print(f"[INFO] Connected to server at {addr}", flush=True)
            break
        except KeyboardInterrupt:
            print("\n[INFO] Client exiting.")
            return
        except (ConnectionRefusedError, OSError):
            print(f"[INFO] Server not ready at {addr}, retrying in 1s…", flush=True)
            s.close()
            import socket as _socket
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            import time
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n[INFO] Client exiting.")
            return

    stop_evt = threading.Event()
    receiver = threading.Thread(target=_recv_loop, args=(s, stop_evt, _VERBOSE_LEVEL), daemon=True)
    receiver.start()

    wfile = s.makefile("w")

    try:
        while True:
            if stop_evt.is_set():
                print("[INFO] Disconnected from server. Exiting client.")
                break

            # Non-blocking prompt when server disconnected: input would still block.
            # Use select on stdin to avoid hang after disconnection.
            import sys
            import select
            if not locals().get("_prompt_shown", False):
                _prompt()
                _prompt_shown = True  # type: ignore[var-annotated]

            ready, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not ready:
                continue
            user_input = sys.stdin.readline().rstrip("\n")
            _prompt_shown = False
            if not user_input:
                continue
            if user_input.startswith("/chat "):
                user_input = f"CHAT {user_input[6:]}"
            wfile.write(user_input + "\n")
            wfile.flush()
    except KeyboardInterrupt:
        print("\n[INFO] Client exiting.")
    finally:
        stop_evt.set()


if __name__ == "__main__":  # pragma: no cover
    main()
