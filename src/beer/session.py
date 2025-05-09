"""Two-player game session logic for the BEER server (Tiers 1–2).

The class in this module manages a *single* match between exactly two
connected clients.  Each match is executed in its own daemon thread and
communicates with clients via a *very* simple line-based protocol:

Client → Server commands
-----------------------
FIRE <coord>   Shoot at the given coordinate (e.g. FIRE B5)
QUIT           Concede the match and disconnect

Server → Client messages
-----------------------
START <you|opp>          Sent at the beginning, tells the client whether it goes first.
GRID                    Followed by 11 lines (header + 10 rows) representing *your* current
                        view of the opponent's board.  Ends with a blank line.
HIT <coord>             Your shot was a hit (and potentially sinks later).
MISS <coord>            Your shot missed.
SUNK <ship>             You have just sunk the named ship.
WIN                     You won the match – all enemy ships sunk or opponent timed-out.
LOSE                    You lost the match.
INFO <text>             Any other informational message.
ERR <text>              Invalid command received; round is repeated.

For Tier 2 we additionally implement:
• 30 s inactivity timeout per player turn.
• Graceful handling of unexpected disconnects.
• Automatic cleanup and socket closing after the match.

The visualisation of the board is intentionally minimal (ASCII grid) so the
existing reference `client.py` continues to work.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import socket
import threading
import time
import select
from typing import TextIO, Any

from .battleship import Board, SHIPS
from .common import PacketType, send_pkt, recv_pkt

COORD_RE = re.compile(r"^[A-J](10|[1-9])$")  # Valid 10×10 coords
TURN_TIMEOUT = 30  # seconds

# Global registry mapping reconnect tokens → ongoing GameSession
TOKEN_REGISTRY: dict[str, "GameSession"] = {}


class GameSession(threading.Thread):
    """Thread managing a single two-player match."""

    def __init__(self, p1: socket.socket, p2: socket.socket):
        """Create a thread that manages a full two-player match.

        Args:
            p1/p2: Already-accepted TCP sockets for player 1 and 2. The
                constructor converts them to text I/O wrappers and prepares
                per-player boards, reconnect tokens, and spectator tracking.
        """
        super().__init__(daemon=True)
        self.p1_sock = p1
        self.p2_sock = p2
        self.p1_file_r: TextIO = p1.makefile("r")
        self.p1_file_w: TextIO = p1.makefile("w")
        self.p2_file_r: TextIO = p2.makefile("r")
        self.p2_file_w: TextIO = p2.makefile("w")
        # Each player gets their *own* hidden board.
        self.board_p1 = Board()
        self.board_p2 = Board()
        self.board_p1.place_ships_randomly(SHIPS)
        self.board_p2.place_ships_randomly(SHIPS)
        self.spectator_w_files: list[TextIO] = []
        self._lock = threading.Lock()
        self._seq = 0

        # Reconnect support (Tier 3)
        self.token_p1 = secrets.token_hex(4)
        self.token_p2 = secrets.token_hex(4)
        TOKEN_REGISTRY[self.token_p1] = self
        TOKEN_REGISTRY[self.token_p2] = self

        self._event_p1 = threading.Event()
        self._event_p2 = threading.Event()

    # -------------------- helpers --------------------
    def _send(
        self,
        w: TextIO,
        msg: str | None = None,
        ptype: PacketType = PacketType.GAME,
        obj: Any | None = None,
    ) -> None:
        """Send a framed packet to *w* and mirror it to spectators.

        Legacy plain-text writes have been removed – every participant now
        receives only the binary Tier-4 frame.  A minimal JSON payload is
        constructed when *obj* is omitted so the client can still print the
        human-readable *msg* string.
        """
        payload = obj if obj is not None else {"msg": msg}
        seq = self._seq
        # Send to primary recipient
        with contextlib.suppress(Exception):
            send_pkt(w.buffer, ptype, seq, payload)  # type: ignore[arg-type]
            w.buffer.flush()
        # Mirror to spectators
        for spec in list(self.spectator_w_files):
            try:
                send_pkt(spec.buffer, ptype, seq, payload)  # type: ignore[arg-type]
                spec.buffer.flush()
            except Exception:
                self.spectator_w_files.remove(spec)
        self._seq += 1

    def _send_grid(self, w: TextIO, board: Board) -> None:
        """Send the attacker (and spectators) their current view of *board*."""
        grid_payload = {
            "type": "grid",
            "rows": [
                " ".join(board.display_grid[r][c] for c in range(board.size))
                for r in range(board.size)
            ],
        }
        self._send(w, "GRID", PacketType.GAME, grid_payload)

    # -------------------- gameplay --------------------
    def run(self) -> None:  # noqa: C901 complexity – fine for server thread
        """Main game-loop executed in its own thread until the match ends."""
        # sourcery skip: low-code-quality
        try:
            # Inform players of their order – P1 starts, include reconnect token
            self._send(self.p1_file_w, f"START you {self.token_p1}")
            self._send(self.p2_file_w, f"START opp {self.token_p2}")
            current_player = 1

            while True:
                attacker_r, attacker_w, defender_board, defender_name = self._select_players(current_player)
                # Identify defender streams for out-of-turn monitoring
                defender_idx = 2 if current_player == 1 else 1
                defender_r, defender_w = self._file_pair(defender_idx)

                # Send the attacker their current opponent grid view
                self._send_grid(attacker_w, defender_board)
                # Request coordinate
                self._send(attacker_w, "INFO Your turn – FIRE <coord> or QUIT")

                coord = self._receive_coord(attacker_r, attacker_w, defender_r, defender_w)
                if coord is None:  # disconnect → start reconnection timer
                    waiting_token = self.token_p1 if current_player == 1 else self.token_p2
                    waiter_event = self._event_p1 if current_player == 1 else self._event_p2
                    self._send(attacker_w, "INFO Disconnected. Waiting 60 s for reconnect...")
                    start_wait = time.time()
                    while time.time() - start_wait < 60:
                        if waiter_event.wait(timeout=1):
                            # reconnected
                            attacker_r, attacker_w = self._file_pair(current_player)
                            break
                    else:
                        winner = 2 if current_player == 1 else 1
                        self._conclude(winner, reason="timeout/disconnect")
                        return

                if coord == "QUIT":
                    winner = 2 if current_player == 1 else 1
                    self._conclude(winner, reason="concession")
                    return

                row, col = coord  # tuple[int, int]
                result, sunk_name = defender_board.fire_at(row, col)
                # Notify attacker of outcome
                if result == "hit":
                    self._send(attacker_w, f"HIT {self._coord_str(row, col)}")
                    if sunk_name:
                        self._send(attacker_w, f"SUNK {sunk_name}")
                elif result == "miss":
                    self._send(attacker_w, f"MISS {self._coord_str(row, col)}")
                elif result == "already_shot":
                    self._send(attacker_w, "ERR Already shot there – choose again")
                    continue  # repeat turn

                # Check game-over
                if defender_board.all_ships_sunk():
                    self._conclude(current_player, reason="fleet destroyed")
                    return

                # Next player's turn
                current_player = 2 if current_player == 1 else 1
        finally:
            # Always close sockets
            with self._lock:
                for sock in (self.p1_sock, self.p2_sock):
                    with contextlib.suppress(Exception):
                        sock.shutdown(socket.SHUT_RDWR)
                    sock.close()

    # -------------------- internal utilities --------------------
    def _select_players(self, current: int):
        if current == 1:
            return self.p1_file_r, self.p1_file_w, self.board_p2, "Player 2"
        return self.p2_file_r, self.p2_file_w, self.board_p1, "Player 1"

    def _file_pair(self, player_idx: int):
        return (self.p1_file_r, self.p1_file_w) if player_idx == 1 else (self.p2_file_r, self.p2_file_w)

    def _receive_coord(self, r: TextIO, w: TextIO, defender_r: TextIO, defender_w: TextIO):
        """Wait for a valid FIRE from *r* while tolerating chat/quit from both sides.

        We block up to TURN_TIMEOUT, but also poll *defender_r* so that out-of-turn
        traffic can be handled immediately (ERR/CHAT/QUIT).  This keeps the game
        responsive and fixes the earlier bug where a premature FIRE could break
        framing.

        Returns:
            tuple[int,int] – coordinate from *r*
            "QUIT"         – the attacker conceded
            None           – timeout or disconnect
        """
        start = time.time()
        att_sock: socket.socket = r.buffer.raw._sock  # type: ignore[attr-defined]
        def_sock: socket.socket = defender_r.buffer.raw._sock  # type: ignore[attr-defined]

        while True:
            remaining = TURN_TIMEOUT - (time.time() - start)
            if remaining <= 0:
                return None
            # Wait until either socket has data or timeout expires
            readable, _, _ = select.select([att_sock, def_sock], [], [], remaining)
            if not readable:
                return None  # timeout

            for sock in readable:
                file = r if sock is att_sock else defender_r
                line = file.readline()
                if not line:  # disconnect
                    return None if sock is att_sock else "DEFENDER_LEFT"
                line = line.strip()
                upper = line.upper()

                if sock is def_sock:
                    # Defender is not on turn
                    if upper.startswith("CHAT "):
                        chat_txt = line[5:].strip()
                        idx = 2 if file is defender_r else 1
                        chat_payload = {"name": f"P{idx}", "msg": chat_txt}
                        self._send(self.p1_file_w, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
                        self._send(self.p2_file_w, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
                        for spec in list(self.spectator_w_files):
                            self._send(spec, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
                        continue
                    elif upper == "QUIT":
                        winner = 1 if file is defender_r else 2
                        self._conclude(winner, reason="concession")
                        return None
                    elif upper.startswith("FIRE "):
                        self._send(defender_w, "ERR Not your turn")
                        continue  # keep waiting for attacker
                    else:
                        self._send(defender_w, "ERR Syntax: FIRE <A-J1-10> or QUIT")
                        continue
                else:  # Attacker's own input
                    if upper.startswith("CHAT "):
                        chat_txt = line[5:].strip()
                        idx = 1 if file is self.p1_file_r else 2
                        chat_payload = {"name": f"P{idx}", "msg": chat_txt}
                        self._send(self.p1_file_w, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
                        self._send(self.p2_file_w, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
                        for spec in list(self.spectator_w_files):
                            self._send(spec, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
                        continue
                    if upper == "QUIT":
                        return "QUIT"
                    if upper.startswith("FIRE "):
                        coord_str = line[5:].strip().upper()
                        if COORD_RE.match(coord_str):
                            row = ord(coord_str[0]) - ord('A')
                            col = int(coord_str[1:]) - 1
                            return (row, col)
                        self._send(w, "ERR Syntax: FIRE <A-J1-10> or QUIT")

    def _conclude(self, winner: int, *, reason: str) -> None:
        loser = 2 if winner == 1 else 1
        win_w = self.p1_file_w if winner == 1 else self.p2_file_w
        lose_w = self.p2_file_w if winner == 1 else self.p1_file_w
        self._send(win_w, "WIN")
        self._send(lose_w, "LOSE")
        self._send(win_w, f"INFO Victory by {reason}.")
        self._send(lose_w, f"INFO Defeat by {reason}.")

    @staticmethod
    def _coord_str(row: int, col: int) -> str:  # Helper for "HIT B5"
        return f"{chr(ord('A') + row)}{col + 1}"

    # ---------------- spectator API -----------------
    def add_spectator(self, sock: socket.socket) -> None:
        """Register an additional read-only client."""
        with self._lock:
            wfile = sock.makefile("w")
            self.spectator_w_files.append(wfile)
            self._send(wfile, "INFO You are now spectating the current match.")

    # ---------------- reconnect API -----------------
    def attach_player(self, token: str, sock: socket.socket) -> bool:
        """Attempt to reattach a disconnected player given their reconnect token."""
        if token == self.token_p1:
            self.p1_sock = sock
            self.p1_file_r = sock.makefile("r")
            self.p1_file_w = sock.makefile("w")
            self._event_p1.set()
            return True
        if token == self.token_p2:
            self.p2_sock = sock
            self.p2_file_r = sock.makefile("r")
            self.p2_file_w = sock.makefile("w")
            self._event_p2.set()
            return True
        return False
