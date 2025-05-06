"""Server wrapper script placed inside the installable package.

This is functionally identical to the legacy top-level `server.py`, but lives in
`src/beer` to be importable as a module entry-point (see `pyproject.toml`).
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys

from .session import GameSession, TOKEN_REGISTRY
from .common import enable_encryption, DEFAULT_KEY

HOST = os.getenv("BEER_HOST", "127.0.0.1")
PORT = int(os.getenv("BEER_PORT", "5000"))


def _handle_cli_flags(argv: list[str]) -> None:
    """Parse --secure[=<hex>] and enable encryption if requested."""
    for arg in argv[1:]:
        if arg.startswith("--secure"):
            if "=" in arg:
                _, key_hex = arg.split("=", 1)
                key = bytes.fromhex(key_hex)
            else:
                key = DEFAULT_KEY
            enable_encryption(key)
            print("[INFO] AES-CTR encryption ENABLED")


def main() -> None:  # pragma: no cover – side-effect entrypoint
    """Lobby server that continuously matches pairs of clients.

    Tier-2 behaviour:
    • Unlimited clients may connect; first two are matched, extras wait in a queue.
    • The server stays alive to host multiple games sequentially without restart.
    """

    # Parse flags before anything else.
    _handle_cli_flags(sys.argv)

    print(f"[INFO] BEER server listening on {HOST}:{PORT}")
    lobby: list[socket.socket] = []
    current_session: GameSession | None = None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen()

        try:
            while True:
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
                # If there's an active session, add as spectator
                if current_session and current_session.is_alive():
                    current_session.add_spectator(conn)
                    print("[INFO] Added new spectator to ongoing game")
                    continue

                # Otherwise join lobby
                lobby.append(conn)

                if len(lobby) >= 2:
                    p1 = lobby.pop(0)
                    p2 = lobby.pop(0)
                    print("[INFO] Launching new game session")
                    current_session = GameSession(p1, p2)
                    current_session.start()
        except KeyboardInterrupt:
            print("[INFO] Shutting down server (KeyboardInterrupt)")
        finally:
            for sock in lobby:
                with contextlib.suppress(Exception):
                    sock.shutdown(socket.SHUT_RDWR)
                sock.close()


if __name__ == "__main__":  # pragma: no cover
    main()
