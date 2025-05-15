"""Server wrapper script placed inside the installable package.

This is functionally identical to the legacy top-level `server.py`, but lives in
`src/beer` to be importable as a module entry-point (see `pyproject.toml`).
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import threading
import time
import logging
import argparse

from .session import GameSession, TOKEN_REGISTRY
from .common import enable_encryption, DEFAULT_KEY
from .battleship import SHIPS
from . import config as _cfg
from .events import Event
from .common import PacketType
from .router import EventRouter

HOST = _cfg.DEFAULT_HOST
PORT = _cfg.DEFAULT_PORT

# Optional single-ship mode
ONE_SHIP_LIST = [("Carrier", 5)]
USE_ONE_SHIP = False

# Initialize module-level logger
logger = logging.getLogger(__name__)


def _parse_cli_flags(argv: list[str]) -> None:
    """Parse --secure[=<hex>] and enable encryption if requested."""
    global USE_ONE_SHIP
    for arg in argv[1:]:
        if arg.startswith("--secure"):
            if "=" in arg:
                _, key_hex = arg.split("=", 1)
                key = bytes.fromhex(key_hex)
            else:
                key = DEFAULT_KEY
            enable_encryption(key)
            print("[INFO] AES-CTR encryption ENABLED")
        elif arg in {"--one-ship", "--solo"}:
            USE_ONE_SHIP = True
            print("[INFO] Running in ONE-SHIP mode (Carrier only)")


def main() -> None:  # pragma: no cover – side-effect entrypoint
    """Lobby server that continuously matches pairs of clients.

    Tier-2 behaviour:
    • Unlimited clients may connect; first two are matched, extras wait in a queue.
    • The server stays alive to host multiple games sequentially without restart.
    """

    # Parse flags before anything else.
    parser = argparse.ArgumentParser(description="BEER server")
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
        help="Increase verbosity.",
    )
    parser.add_argument(
        "-s",
        "--silent",
        "-q",
        "--quiet",
        dest="silent",
        action="store_true",
        help="Suppress all output.",
    )

    args = parser.parse_args()

    # Set the BEER_DEBUG environment variable based on the --debug flag
    if args.debug:
        os.environ["BEER_DEBUG"] = "1"

    # Determine effective verbosity: silent → -1, otherwise 0/1/2 (count of -v)
    eff_verbose = -1 if args.silent else args.verbose

    logging.basicConfig(level=logging.DEBUG if _cfg.DEBUG else logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    _parse_cli_flags(sys.argv)

    print(f"[INFO] BEER server listening on {HOST}:{PORT}")
    lobby: list[socket.socket] = []
    current_session: GameSession | None = None
    session_ready = threading.Event()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen()

        def _try_pair_lobby():
            nonlocal current_session, session_ready
            while len(lobby) >= 2 and (not current_session or not current_session.is_alive()):
                p1 = lobby.pop(0)
                p2 = lobby.pop(0)
                print("[INFO] Launching new game session")
                ships_list = ONE_SHIP_LIST if USE_ONE_SHIP else SHIPS
                session_ready.clear()
                current_session = GameSession(p1, p2, ships=ships_list, session_ready=session_ready)

                # Temporary event router – converts to debug log for now.
                router = EventRouter(current_session)
                current_session.subscribe(router)

                def _monitor_session(sess: GameSession) -> None:
                    sess.join()
                    if sess.winner is not None:
                        print(f"[INFO] Match completed – P{sess.winner} won by {sess.win_reason}.")
                    print("[INFO] Waiting for new players…")
                    _try_pair_lobby()  # Try to pair again after this game ends

                current_session.start()
                session_ready.wait()  # Wait until session signals ready for spectators
                threading.Thread(target=_monitor_session, args=(current_session,), daemon=True).start()

        # Heartbeat disabled – rely on TCP disconnects instead

        try:
            while True:
                # Accept new connection (blocking)
                conn, addr = server_sock.accept()
                print(f"[INFO] Client connected from {addr}")

                # Try to read first line (non-blocking small timeout) to detect TOKEN reconnect.
                conn.settimeout(2)
                try:
                    first_bytes = conn.recv(64, socket.MSG_PEEK)
                except Exception:
                    first_bytes = b""
                conn.settimeout(None)

                if first_bytes.startswith(b"TOKEN "):
                    rfile = conn.makefile("r")
                    token_line = rfile.readline().strip()
                    token = token_line.split()[1] if len(token_line.split()) > 1 else ""
                    session = TOKEN_REGISTRY.get(token)
                    if session and session.attach_player(token, conn):
                        print("[INFO] Reattached player via token")
                    else:
                        conn.close()
                        print("[WARN] Invalid reconnect token—connection dropped")
                    continue

                # Always append to lobby
                lobby.append(conn)
                print(f"[DEBUG] Client added to lobby (len={len(lobby)})")
                _try_pair_lobby()

                # After pairing, attach all extra clients as spectators
                if current_session and current_session.is_alive() and session_ready.is_set():
                    while len(lobby) > 0:
                        spectator = lobby.pop(0)
                        current_session.add_spectator(spectator)
                        print("[DEBUG] Spectator attached from lobby")
        except KeyboardInterrupt:
            print("[INFO] Shutting down server (KeyboardInterrupt)")
        finally:
            for sock in lobby:
                with contextlib.suppress(Exception):
                    sock.shutdown(socket.SHUT_RDWR)
                sock.close()


if __name__ == "__main__":  # pragma: no cover
    main()
