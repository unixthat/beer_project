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
from .cheater import Cheater
from .common import send_pkt
from .keyexchange import client_handshake
from .encryption import enable_encryption
from . import encryption as _encryption

HOST = _cfg.DEFAULT_HOST
PORT = _cfg.DEFAULT_PORT

# Logging setup respects global DEBUG flag
logging.basicConfig(
    level=logging.DEBUG if _cfg.DEBUG else logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ------------------- PID-token handshake token -------------------
# Handshake token: default to the parent shell's PID for reconnect persistence, overrideable by BEER_TOKEN env var
TOKEN = os.getenv("BEER_TOKEN", f"PID{os.getppid()}")
# Inform user of the token in use
logger.info("Using handshake TOKEN=%s", TOKEN)

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


# Flag that controls whether the main loop has shown the ">> " prompt
_prompt_shown = False


def _recv_loop(
    sock: socket.socket,
    stop_evt: threading.Event,
    verbose: int,
    cheat_mode: bool,
    cheater: Cheater,
    bw,  # shared binary writer for both reliability and game commands
) -> None:  # pragma: no cover
    global _prompt_shown

    """Continuously print messages from the server (framed packets only)."""
    global TOKEN
    br = sock.makefile("rb")  # buffered reader
    # Attach our shared writer for reliability (ACK/NAK control)
    setattr(br, "_writer", bw)
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
                logger.debug("recv_pkt() – about to read packet from socket")
                ptype, seq, obj = recv_pkt(br)  # type: ignore[arg-type]
                logger.debug("recv_pkt() – received ptype=%s seq=%d obj=%r", ptype, seq, obj)
            except IncompleteError:
                # Stream closed cleanly – exit receiver loop without warning.
                stop_evt.set()
                break
            except FrameError as exc:
                logger.warning("recv_pkt() frame error: %s", exc)
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
                        print(f"\r{msg}")
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
        logger.exception("Receiver thread crashed: %r", exc)
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
        logger.info("Encryption enabled in client")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        _client(s, args, cheat_mode=args.win)


# Internal client loop invoked from main
def _client(s, args, cheat_mode: bool = False):
    global _prompt_shown

    addr = (args.host, args.port)
    # Retry loop: once-per-second until connected or interrupted
    while True:
        try:
            s.connect(addr)
            # Always send PID handshake for initial join or reconnect
            try:
                s.sendall(f"TOKEN {TOKEN}\n".encode())
                logger.debug("Sending TOKEN handshake: %s", TOKEN)
            except Exception:
                pass
            logger.info("Connected to server at %s", addr)
            break
        except KeyboardInterrupt:
            logger.info("Client exiting")
            return
        except (ConnectionRefusedError, OSError):
            logger.info("Server not ready at %s, retrying in 1s…", addr)
            s.close()
            import socket as _socket

            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            import time

            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Client exiting")
            return

    # Perform ECDH encryption handshake if no static key is set
    if _encryption._secret_key is None:
        client_handshake(s)
        logger.debug("Completed client ECDH handshake and enabled encryption")
    stop_evt = threading.Event()
    cheater = Cheater() if cheat_mode else None
    # Single binary writer for both reliability (ACK/NAK) and user commands
    wbuf = s.makefile("wb")
    # Start the receiver thread with our shared writer
    receiver = threading.Thread(
        target=_recv_loop,
        args=(s, stop_evt, _VERBOSE_LEVEL, cheat_mode, cheater, wbuf),
        daemon=True,
    )
    receiver.start()
    # Use wbuf to send all framed game commands
    client_seq = 0

    try:
        while True:
            if stop_evt.is_set():
                logger.info("Disconnected from server. Exiting client.")
                break

            # auto-fire in win mode (only when cheater was notified)
            if cheat_mode and cheater and cheater._seeded:
                coord = cheater.next_shot()
                if coord is None:
                    # not ready or out of targets
                    if not cheater._turn_ready:
                        continue
                    logger.info("All ships fired, exiting cheat-client.")
                    break
                # Debug: show auto-fire send
                auto_cmd = f"FIRE {coord}"
                logger.debug("client pre-auto-send – seq=%d cmd=%r", client_seq, auto_cmd)
                send_pkt(wbuf, PacketType.GAME, client_seq, auto_cmd)
                wbuf.flush()
                logger.debug("client post-auto-send – seq=%d cmd=%r", client_seq, auto_cmd)
                client_seq += 1
                _prompt_shown = False
                continue

            # normal prompt…
            if not _prompt_shown:
                _prompt()
                _prompt_shown = True

            import sys, select
            ready, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not ready:
                continue
            user_input = sys.stdin.readline().rstrip("\n")
            _prompt_shown = False
            if not user_input:
                continue
            if user_input.upper() == "QUIT":
                logger.info("Exiting client per user request.")
                break
            parts = user_input.strip().split(" ", 1)
            if parts[0].lower() == "/chat" and len(parts) > 1:
                user_input = f"CHAT {parts[1]}"
            # Debug: show exactly what we're about to send
            logger.debug("client pre-send – seq=%d cmd=%r", client_seq, user_input)
            send_pkt(wbuf, PacketType.GAME, client_seq, user_input)
            wbuf.flush()
            logger.debug("client post-send – seq=%d cmd=%r", client_seq, user_input)
            client_seq += 1
    except KeyboardInterrupt:
        logger.info("Client exiting")
    finally:
        stop_evt.set()


if __name__ == "__main__":  # pragma: no cover
    main()
