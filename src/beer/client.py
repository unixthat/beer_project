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
import sys
import queue

from .common import (
    PacketType,
    FrameError,
    IncompleteError,
    CrcError,
    recv_pkt,
    send_pkt,
    enable_encryption,
    DEFAULT_KEY,
)
from .battleship import SHIP_LETTERS
from . import config as _cfg
from .cheater import Cheater
from .io_utils import send as io_send

HOST = _cfg.DEFAULT_HOST
PORT = _cfg.DEFAULT_PORT

# Logging setup respects global DEBUG flag
logging.basicConfig(
    level=logging.DEBUG if _cfg.DEBUG else logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------- PID-token handshake token -------------------
# Handshake token: default to the parent (shell) PID so it stays constant per terminal
TOKEN = os.getenv("BEER_TOKEN", f"PID{os.getppid()}")
# Inform user of the token in use
print(f"[INFO] Using handshake TOKEN='{TOKEN}'")

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


try:
    import readline
except ImportError:
    readline = None

def _prompt() -> None:
    """Display the user-input prompt, preserving any typed text."""
    # Always clear the current line and print a fresh blank prompt
    sys.stdout.write("\r\033[K>> ")
    sys.stdout.flush()


# Flag that controls whether the main loop has shown the ">> " prompt
_prompt_shown = False


def _recv_loop(
    sock: socket.socket, stop_evt: threading.Event, verbose: int, cheat_mode: bool, cheater: Cheater
) -> None:  # pragma: no cover
    global _prompt_shown

    """Continuously print messages from the server (framed packets only)."""
    global TOKEN
    br = sock.makefile("rb")  # binary reader for framed packets
    bw = sock.makefile("wb")  # binary writer for ACK/NAK
    # Track which player slot we're in (1=you, 2=opponent)
    my_slot: int | None = None

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
            nonlocal last_own
            last_own = rows
            # do not seed cheater from own grid reveal
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
        # Compare against our slot to know if *we* won
        if my_slot is not None and winner == my_slot:
            print(f"YOU WON with {shots} shots")
        else:
            print(f"YOU LOST – opponent won with {shots} shots")

    def h_opp_grid(obj: dict) -> None:
        # Reveal hidden opponent grid only in --win (cheat) mode
        if not cheat_mode:
            return
        rows = obj["rows"]
        # Seed the cheater logic
        cheater.feed_grid(rows)
        # Display the hidden grid
        if verbose >= 0:
            print("\n[Opponent Hidden Ships]")
            _print_grid(rows)

    handlers: Dict[str, Callable[[dict], None]] = {
        "spec_grid": h_spec_grid,
        "grid": h_grid,
        "shot": h_shot,
        "chat": h_chat,
        "end": h_end,
        "opp_grid": h_opp_grid,
    }

    try:
        while True:
            try:
                ptype, seq, obj = recv_pkt(br)  # type: ignore[arg-type]
                # Acknowledge receipt
                send_pkt(bw, PacketType.ACK, seq, None)
            except IncompleteError:
                # Stream closed cleanly – exit receiver loop without warning.
                stop_evt.set()
                break
            except CrcError as e:
                if verbose >= 0:
                    print(f"[WARN] CRC mismatch on seq {e.seq}, requesting retransmission.")
                # Request retransmission of the bad frame
                send_pkt(bw, PacketType.NAK, e.seq, None)
                continue
            except FrameError as exc:
                if verbose >= 0:
                    print(f"[WARN] Frame error: {exc}.")
                stop_evt.set()
                break
            except Exception:
                # Socket closed or unreadable – terminate receiver thread.
                stop_evt.set()
                break

            if ptype in (PacketType.GAME, PacketType.OPP_GRID) and isinstance(obj, dict):
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
                    # START you: new token assignment
                    if msg.startswith("START you "):
                        # Extract token and persist it
                        parts = msg.split(maxsplit=2)
                        if len(parts) >= 3:
                            TOKEN = parts[2]
                        # We are Player 1
                        my_slot = 1
                        print(msg)
                        continue
                    # START opp: just display
                    if msg.startswith("START opp "):
                        # We are Player 2
                        my_slot = 2
                        print(msg)
                        continue
                    # Handle unknown-token error silently: reset persistent token, do not display
                    if msg.startswith("ERR Unknown token "):
                        # Reset to this process's parent (shell) PID token for fresh join
                        TOKEN = f"PID{os.getppid()}"
                        continue
                    # INFO and other ERR messages shown
                    if (
                        msg.startswith("INFO ")
                        or (msg.startswith("ERR ") and not msg.startswith("ERR Unknown token "))
                        or msg.startswith("[INFO] ")
                    ):
                        # Print server INFO/ERR message and immediately reprint prompt
                        print(f"\r{msg}", flush=True)
                        # Reprint the input prompt so it's visible immediately
                        _prompt()
                        # Reset prompt when the shooter should act again
                        if msg.startswith("INFO YOUR TURN") or msg.startswith("INFO Opponent has reconnected"):
                            _prompt_shown = False
                            if cheat_mode and cheater:
                                cheater.notify_turn()
                        continue
                    # Raw/unrecognized frames at verbose>=1
                    if verbose >= 1 and "raw" not in _cfg.QUIET_CATEGORIES:
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


def main() -> None:  # pragma: no cover – CLI entry
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
    parser.add_argument(
        "--win",
        action="store_true",
        help="Cheat mode: auto‐fire every opponent ship cell exactly once",
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
        _client(s, args, cheat_mode=args.win)


# Internal client loop invoked from main
def _client(s, args, cheat_mode: bool = False):
    addr = (args.host, args.port)
    # Retry loop: connect or exit
    while True:
        try:
            s.connect(addr)
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
            try:
                s.close()
            except Exception:
                pass
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        time.sleep(1)
    stop_evt = threading.Event()
    cheater = Cheater() if cheat_mode else None
    receiver = threading.Thread(target=_recv_loop, args=(s, stop_evt, _VERBOSE_LEVEL, cheat_mode, cheater), daemon=True)
    receiver.start()

    # Spawn input thread for non-blocking, readline-powered prompt
    input_queue = queue.Queue()
    def _input_thread():
        while not stop_evt.is_set():
            try:
                line = input(">> ")
            except (EOFError, KeyboardInterrupt):
                # Signal shutdown and unblock main loop
                stop_evt.set()
                input_queue.put(None)
                break
            input_queue.put(line)
    threading.Thread(target=_input_thread, daemon=True).start()

    # Set up framed writer and sequence counter
    wfile = s.makefile("w")
    client_seq = 0

    try:
        while True:
            if stop_evt.is_set():
                # Ensure a clear newline so the shell prompt appears correctly
                print()
                print("[INFO] Disconnected from server. Exiting client.")
                break

            # auto-fire in win mode
            if cheat_mode and cheater and cheater._seeded:
                coord = cheater.next_shot()
                if coord is None:
                    if not cheater._turn_ready:
                        continue
                    print("[INFO] All ships fired, exiting cheat-client.")
                    break
                # Send framed FIRE command
                io_send(wfile, client_seq, PacketType.GAME, msg=f"FIRE {coord}")
                client_seq += 1
                continue

            # fetch user input
            try:
                user_input = input_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if user_input is None:
                break
            text = user_input.strip()
            if not text:
                continue
            if text.upper() == "QUIT":
                print("[INFO] Exiting client per user request.")
                break
            # Send framed command
            io_send(wfile, client_seq, PacketType.GAME, msg=text)
            client_seq += 1
    except KeyboardInterrupt:
        print("\n[INFO] Client exiting.")
    finally:
        stop_evt.set()


if __name__ == "__main__":  # pragma: no cover
    main()
