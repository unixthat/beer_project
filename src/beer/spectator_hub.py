import threading
import socket
from typing import TextIO, Any, List, Callable
from .io_utils import grid_rows
from .battleship import Board
import contextlib


class SpectatorHub:
    """Manage spectators: add, broadcast messages, send board snapshots, and promote to player slot."""

    def __init__(self, notify_fn: Callable[[TextIO, str | None, Any | None], None]):
        self._lock = threading.Lock()
        self._sockets: List[socket.socket] = []
        self._writers: List[TextIO] = []
        self._notify = notify_fn
        self._tokens: dict[socket.socket, str | None] = {}

    def add(self, sock: socket.socket, token: str | None) -> None:
        """Register a new spectator and notify them."""
        with self._lock:
            wfile = sock.makefile("w")
            self._sockets.append(sock)
            self._writers.append(wfile)
            self._notify(wfile, "INFO YOU ARE NOW SPECTATING", None)
            self._tokens[sock] = token

    def broadcast(self, msg: str) -> None:
        """Broadcast a text message to all spectators."""
        with self._lock:
            for sock, wfile in list(zip(self._sockets, self._writers)):
                try:
                    self._notify(wfile, msg, None)
                except Exception:
                    # Remove broken spectator
                    self._sockets.remove(sock)
                    self._writers.remove(wfile)
                    with contextlib.suppress(Exception):
                        sock.close()

    def broadcast_msgs(self, *msgs: str) -> None:
        """Broadcast multiple text messages to all spectators in one pass."""
        with self._lock:
            for sock, wfile in list(zip(self._sockets, self._writers)):
                try:
                    for msg in msgs:
                        self._notify(wfile, msg, None)
                except Exception:
                    # Remove broken spectator
                    self._sockets.remove(sock)
                    self._writers.remove(wfile)
                    with contextlib.suppress(Exception):
                        sock.close()

    def snapshot(self, board_p1: Any, board_p2: Any) -> None:
        """Send a full dual-board snapshot (with ships revealed) to all spectators."""
        rows_p1 = grid_rows(board_p1, reveal=True)
        rows_p2 = grid_rows(board_p2, reveal=True)
        payload = {"type": "spec_grid", "rows_p1": rows_p1, "rows_p2": rows_p2}
        with self._lock:
            for sock, wfile in list(zip(self._sockets, self._writers)):
                try:
                    self._notify(wfile, None, payload)
                except Exception:
                    # Remove broken spectator
                    self._sockets.remove(sock)
                    self._writers.remove(wfile)
                    with contextlib.suppress(Exception):
                        sock.close()

    def empty(self) -> bool:
        """Return True if there are no waiting spectators."""
        with self._lock:
            return not self._sockets

    def is_spectator(self, file: TextIO) -> bool:
        """
        Return True if the given TextIO reader corresponds to a spectator socket.
        """
        try:
            sock = file.buffer.raw._sock  # type: ignore[attr-defined]
        except Exception:
            return False
        with self._lock:
            return sock in self._sockets

    def promote(self, slot: int, session: Any) -> bool:
        """Promote the next spectator into the given player slot. Returns True if done."""
        with self._lock:
            if not self._writers:
                return False
            new_sock = self._sockets.pop(0)
            new_wfile = self._writers.pop(0)

        # Notify the surviving opponent
        other_idx = 2 if slot == 1 else 1
        other_w = session.p2_file_w if slot == 1 else session.p1_file_w
        self._notify(other_w, f"INFO Opponent disconnected – starting new game (you remain Player {other_idx})", None)

        # Bind the new spectator socket into the player slot
        if slot == 1:
            session.p1_sock = new_sock
            session.p1_file_r = new_sock.makefile("r")
            session.p1_file_w = new_wfile
        else:
            session.p2_sock = new_sock
            session.p2_file_r = new_sock.makefile("r")
            session.p2_file_w = new_wfile

        # Advise the promoted client
        self._notify(new_wfile, "INFO YOU ARE NOW PLAYING – you've replaced the disconnected opponent", None)
        # Extract & register this client's PID-token for the new slot
        token = self._tokens.pop(new_sock, None)
        from .server import PID_REGISTRY
        # Clean up old slot token and install the new one
        if slot == 1:
            old = session.recon.token1
            PID_REGISTRY.pop(old, None)
            session.recon.token1 = token
            session.token_p1 = token
        else:
            old = session.recon.token2
            PID_REGISTRY.pop(old, None)
            session.recon.token2 = token
            session.token_p2 = token
        PID_REGISTRY[token] = session.recon
        # Now reset game session for a fresh match
        session.board_p1 = Board()
        session.board_p2 = Board()
        session._shots = {1: 0, 2: 0}
        session._fired = {1: set(), 2: set()}
        session._half_turn_counter = 0
        session._line_buffer.clear()
        # Start a fresh match handshake
        session._begin_match()
        return True
