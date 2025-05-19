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
import signal
from typing import Optional, Any
import itertools

from .session import GameSession
from .reconnect_controller import ReconnectController
from .common import enable_encryption, DEFAULT_KEY, recv_pkt, send_pkt, PacketType
from .battleship import SHIPS
from . import config as _cfg
from .events import Event
from .router import EventRouter
from .io_utils import send as io_send, grid_rows

HOST = _cfg.DEFAULT_HOST
PORT = _cfg.DEFAULT_PORT

# Optional single-ship mode
ONE_SHIP_LIST = [("Carrier", 5)]
USE_ONE_SHIP = False

# Global PID token counter for new matches
_pid_counter = itertools.count(100000)

# Initialize module-level logger
logger = logging.getLogger(__name__)

# Registry for PID-based reconnect tokens (maps token to ReconnectController)
PID_REGISTRY: dict[str, ReconnectController] = {}


# Add helper for requeue logic
def requeue_players(
    lobby: list[tuple[socket.socket, Optional[str]]],
    winner: tuple[socket.socket, Optional[str]],
    loser: tuple[socket.socket, Optional[str]],
    reason: str,
) -> None:
    """
    Requeue logic: insert winner at front/head, and append loser if reason
    not in {"timeout", "concession"}.
    """
    # Skip requeue if winner socket is already closed
    try:
        if winner[0].fileno() == -1:
            return
    except Exception:
        # Unable to determine fileno; assume alive
        pass
    lobby.insert(0, winner)
    if reason not in {"timeout", "concession"}:
        lobby.append(loser)


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

    # Determine log level from CLI flags:
    if args.silent:
        level = logging.ERROR
    elif args.debug or _cfg.DEBUG:
        level = logging.DEBUG
    elif args.verbose >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _parse_cli_flags(sys.argv)

    logging.info(f"BEER server listening on {HOST}:{PORT}")
    # lobby holds tuples of (conn, reconnect_token)
    lobby: list[tuple[socket.socket, Optional[str]]] = []
    current_session: GameSession | None = None
    session_ready = threading.Event()

    # Broadcast helper: send to every waiting client in the lobby
    def lobby_broadcast(msg: str | None, obj: Any | None = None) -> None:
        for sock, _ in lobby:
            try:
                wfile = sock.makefile("w")
                # if obj is a chat payload, send as CHAT frame
                ptype = PacketType.CHAT if obj and isinstance(obj, dict) and obj.get("type") == "chat" else PacketType.GAME
                io_send(wfile, 0, ptype, msg=msg, obj=obj)
            except Exception:
                pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen()

        # install graceful shutdown handler (per roadmap ID-5)
        def _shutdown(signum, frame):
            # ensure the "C" echo doesn't get stuck on our log line
            sys.stderr.write("\n")
            logger.info("Received signal %s, shutting down", signum)
            server_sock.close()
            sys.exit(0)

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        def _try_pair_lobby():
            nonlocal current_session, session_ready
            while len(lobby) >= 2 and (not current_session or not current_session.is_alive()):
                (c1, token1) = lobby.pop(0)
                (c2, token2) = lobby.pop(0)
                # Prevent duplicate tokens in a new match
                if token1 and token2 and token1 == token2:
                    logging.warning(f"Duplicate token {token1} in lobby; resetting second slot to fresh token")
                    token2 = None
                logging.info("Launching new game session")
                ships_list = ONE_SHIP_LIST if USE_ONE_SHIP else SHIPS
                session_ready.clear()
                # Generate or reuse PID-tokens
                t1 = token1 or f"PID{next(_pid_counter)}"
                t2 = token2 or f"PID{next(_pid_counter)}"
                # Instantiate session (ReconnectController inside will register tokens),
                # passing in our unified lobby broadcast
                current_session = GameSession(
                    c1,
                    c2,
                    ships=ships_list,
                    token_p1=t1,
                    token_p2=t2,
                    session_ready=session_ready,
                    broadcast=lobby_broadcast,
                )

                # Temporary event router – converts to debug log for now.
                router = EventRouter(current_session)
                current_session.subscribe(router)

                # Monitor the match, then re-queue both players (no more "spectators" here)
                def _monitor_session(sess: GameSession) -> None:
                    sess.join()
                    winner = sess.winner or 0
                    reason = sess.win_reason or ""
                    # report with PID tokens
                    winning_tok = sess.token_p1 if winner == 1 else sess.token_p2
                    losing_tok  = sess.token_p2 if winner == 1 else sess.token_p1
                    logger.info(f"Match completed – {winning_tok} won by {reason}")
                    # broadcast concession to waiting spectators
                    if reason == "concession":
                        lobby_broadcast(f"INFO Player {losing_tok} has forfeited – match over", None)
                        logger.info(f"{losing_tok} concedes – match over")
                    # Notify current spectators of the match result
                    shots = getattr(sess, 'win_shots', None) or 0
                    winning_tok = sess.token_p1 if winner == 1 else sess.token_p2
                    losing_tok = sess.token_p2 if winner == 1 else sess.token_p1
                    result_msg = f"INFO {winning_tok} BEAT {losing_tok} IN {shots} SHOTS"
                    # Broadcast result to all waiting spectators
                    lobby_broadcast(result_msg, None)
                    logger.info(f"Spectators notified: {result_msg}")
                    # Re-queue both players back into lobby
                    if winner == 1:
                        w_sock, w_tok = sess.p1_sock, sess.token_p1
                        l_sock, l_tok = sess.p2_sock, sess.token_p2
                    else:
                        w_sock, w_tok = sess.p2_sock, sess.token_p2
                        l_sock, l_tok = sess.p1_sock, sess.token_p1
                    requeue_players(lobby, (w_sock, w_tok), (l_sock, l_tok), reason)
                    logger.info(f"Lobby requeue: front={w_tok}, back={l_tok} (size={len(lobby)})")
                    # Notify waiting spectators of their updated queue positions
                    # (skip positions 1–2, they're about to start the next match)
                    for pos, (sock, _) in enumerate(lobby, start=1):
                        if pos <= 2:
                            continue
                        try:
                            wfile = sock.makefile("w")
                            io_send(wfile, 0, msg=f"INFO You are number {pos-2} in the queue to play")
                        except Exception:
                            pass
                    # kick off next match if ready
                    _try_pair_lobby()

                current_session.start()
                session_ready.wait()
                threading.Thread(target=_monitor_session, args=(current_session,), daemon=True).start()

        # Heartbeat disabled – rely on TCP disconnects instead

        try:
            while True:
                # Accept new connection (blocking)
                conn, addr = server_sock.accept()
                logger.info(f"Connection from {addr}")
                # Framed handshake: read a GAME packet carrying {"token": ...}
                try:
                    br = conn.makefile("rb")
                    bw = conn.makefile("wb")
                    ptype, seq, obj = recv_pkt(br)  # handshake frame
                    # ACK the handshake so client prunes that seq
                    send_pkt(bw, PacketType.ACK, seq, None)
                    token_str = obj.get("token") if isinstance(obj, dict) else None
                    logger.debug("Received framed handshake token: %r", token_str)
                except Exception:
                    token_str = None
                # Reconnect attempt?
                if token_str:
                    ctrl = PID_REGISTRY.get(token_str)
                    if ctrl:
                        if ctrl.attach_player(token_str, conn):
                            logger.info(f"Reattached via PID-token {token_str}")
                        # don't enqueue as new spectator or pair into play
                        continue
                # Always treat fresh connections as waiting/spectating clients
                lobby.append((conn, token_str))
                # New spectator waiting in lobby
                pos = len(lobby)
                logger.info(f"Lobby update: token {token_str!r} joined (size={pos})")

                # if a game is already in progress, inform the new client:
                if current_session and current_session.is_alive():
                    wfile = conn.makefile("w")
                    # Notify spectator status
                    io_send(wfile, 0, msg="INFO You are now spectating")
                    # Notify queue position
                    io_send(wfile, 0, msg=f"INFO You are currently number {pos} in the queue to play")
                    # Optionally ship them the current board immediately
                    rows_p1 = grid_rows(current_session.board_p1, reveal=True)
                    rows_p2 = grid_rows(current_session.board_p2, reveal=True)
                    lobby_broadcast(None, {"type": "spec_grid", "rows_p1": rows_p1, "rows_p2": rows_p2})

                _try_pair_lobby()
        finally:
            for sock, _ in lobby:
                with contextlib.suppress(Exception):
                    sock.shutdown(socket.SHUT_RDWR)
                sock.close()


if __name__ == "__main__":  # pragma: no cover
    main()
