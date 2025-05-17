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
import socket
import threading
import time
import select
from typing import TextIO, Any, Callable, List

from .battleship import Board, SHIPS, parse_coordinate, SHIP_LETTERS
from .common import PacketType
from .io_utils import send as io_send, send_grid, safe_readline
from .spectator_hub import SpectatorHub
from .reconnect_controller import ReconnectController
from . import config as _cfg
from .events import Event, Category

COORD_RE = re.compile(r"^[A-J](10|[1-9])$")  # Valid 10×10 coords
TURN_TIMEOUT = _cfg.TURN_TIMEOUT  # seconds


class GameSession(threading.Thread):
    """Thread managing a single two-player match."""

    def __init__(self, p1: socket.socket, p2: socket.socket, *, token_p1: str, token_p2: str, ships=None, session_ready=None):
        """Create a thread that manages a full two-player match.

        Args:
            p1/p2: Already-accepted TCP sockets for player 1 and 2. The
                constructor converts them to text I/O wrappers and prepares
                per-player boards, reconnect tokens, and spectator tracking.
        """
        super().__init__(daemon=True)
        self.p1_sock = p1
        self.p2_sock = p2
        # Enable TCP keepalive to detect disconnects promptly
        try:
            self.p1_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self.p2_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass  # Not all platforms support this, but try
        self.p1_file_r: TextIO = p1.makefile("r")
        self.p1_file_w: TextIO = p1.makefile("w")
        self.p2_file_r: TextIO = p2.makefile("r")
        self.p2_file_w: TextIO = p2.makefile("w")
        # Ship roster for this match
        self.ships = ships if ships is not None else SHIPS
        self.session_ready = session_ready

        # Each player gets their *own* hidden board.
        self.board_p1 = Board()
        self.board_p2 = Board()
        self.board_p1.place_ships_randomly(self.ships)
        self.board_p2.place_ships_randomly(self.ships)
        # Spectator streams now managed via SpectatorHub
        # Every *half-turn* (i.e. after each individual shot) we increment
        # this counter; spectators receive a full dual-board update after
        # every *two* shots (both players have acted).
        self._half_turn_counter: int = 0
        self._lock = threading.Lock()
        self._seq = 0

        # Reconnect support (Tier 3) using PID tokens
        self.token_p1 = token_p1
        self.token_p2 = token_p2
        # Modular I/O sequencing and helpers
        self.io_seq = 0
        # Unified send callback for writing to a TextIO
        def _notify(wfile: TextIO, msg: str | None = None, obj: Any | None = None) -> None:
            # Send a GAME packet with text or obj payload
            io_send(wfile, self.io_seq, msg=msg, obj=obj)
            self.io_seq += 1
        self._notify = _notify
        # Convenience for reconnect notifications to player slots
        self._notify_player = lambda slot, txt: self._notify(
            self.p1_file_w if slot == 1 else self.p2_file_w, txt
        )
        # Spectator management
        self.spec = SpectatorHub(self._notify)
        # Reconnect controller (handles wait windows and token reattachment)
        from .server import PID_REGISTRY
        self.recon = ReconnectController(
            _cfg.RECONNECT_TIMEOUT,
            self._notify_player,
            self.token_p1,
            self.token_p2,
            PID_REGISTRY,
        )

        # Out-of-thread result reporting
        self.winner: int | None = None
        self.win_reason: str | None = None

        # Shot counters per player
        self._shots: dict[int, int] = {1: 0, 2: 0}
        # Track fired coords to prevent duplicate shots
        self._fired: dict[int, set[tuple[int,int]]] = {1: set(), 2: set()}

        # Event subscribers
        self._subs: List[Callable[[Event], None]] = []

        # Added for the new run method
        self._line_buffer: dict[int, str] = {}

    # -------------------- helpers --------------------
    # Removed duplicate _send and _send_grid methods; using io_utils.send and send_grid directly

    # ------------------- match handshake helper -------------------
    def _begin_match(self) -> None:
        """Handshake to start or restart a match: START, placement, initial grids, signal ready."""
        # Emit start event and notify both players
        self._emit(Event(Category.TURN, "start", {"token_p1": self.token_p1, "token_p2": self.token_p2}))
        # Notify players of new match and tokens
        self._notify(self.p1_file_w, "INFO New game: you are Player 1")
        self._notify(self.p2_file_w, "INFO New game: you are Player 2")
        # Legacy START frames for compatibility
        self._notify(self.p1_file_w, f"START you {self.token_p1}")
        self._notify(self.p2_file_w, f"START opp {self.token_p2}")

        # Manual placement skipped (random placement used)

        # Initial own-fleet reveal
        send_grid(self.p1_file_w, self.io_seq, self.board_p1, reveal=True); self.io_seq += 1
        send_grid(self.p2_file_w, self.io_seq, self.board_p2, reveal=True); self.io_seq += 1
        # Initial opponent views
        send_grid(self.p1_file_w, self.io_seq, self.board_p2);                self.io_seq += 1
        send_grid(self.p2_file_w, self.io_seq, self.board_p1);                self.io_seq += 1

        # Signal ready for spectators
        if self.session_ready:
            self.session_ready.set()

    # -------------------- gameplay --------------------
    def run(self) -> None:  # noqa: C901 complexity – fine for server thread
        """Main game-loop executed in its own thread until the match ends."""
        try:
            # Start the first match handshake
            self._begin_match()
            current_player = 1

            while True:
                # Poll both sockets for disconnect before each turn
                for idx, (r, w) in enumerate([(self.p1_file_r, self.p1_file_w), (self.p2_file_r, self.p2_file_w)], start=1):
                    sock = r.buffer.raw._sock
                    readable, _, _ = select.select([sock], [], [], 0)
                    if readable:
                        line = safe_readline(r, lambda: self.recon.wait(idx))
                        if not line:
                            print(f"[DEBUG] run: disconnect on player {idx}")
                            # allow a reconnect window first
                            if self.recon.wait(idx):
                                # Original player rejoined: rebind socket
                                new_sock = self.recon.take_new_socket(idx)
                                self._rebind_slot(idx, new_sock)
                                continue    # resume turn with reattached player
                            # then try to promote a spectator
                            if self.spec.promote(idx, self):
                                continue    # resume the same turn with new player
                            # no one to promote → normal conclusion
                            winner = 2 if idx == 1 else 1
                            self._conclude(winner, reason="timeout/disconnect")
                            return

                # Process buffered lines if any
                self._line_buffer.clear()

                attacker_r, attacker_w, defender_board, defender_name = self._select_players(current_player)
                # Identify defender streams for out-of-turn monitoring
                defender_idx = 2 if current_player == 1 else 1
                defender_r, defender_w = self._file_pair(defender_idx)

                # Request coordinate (do NOT mirror to spectators)
                self._notify(attacker_w, "INFO Your turn – FIRE <coord> or QUIT")
                self._emit(Event(Category.TURN, "prompt", {"player": current_player}))

                coord = self._receive_coord(attacker_r, attacker_w, defender_r, defender_w)
                if coord == "DEFENDER_LEFT":
                    # defender dropped mid-turn → try reconnect first
                    if self.recon.wait(defender_idx):
                        # Original defender rejoined: rebind socket
                        new_sock = self.recon.take_new_socket(defender_idx)
                        self._rebind_slot(defender_idx, new_sock)
                        continue     # resume turn with reattached defender
                    # otherwise try to promote a spectator
                    if self.spec.promote(defender_idx, self):
                        continue     # resume same turn with new defender
                    # no one left → end match
                    winner = 2 if current_player == 1 else 1
                    self._conclude(winner, reason="timeout/disconnect")
                    return
                if coord is None:
                    # TURN_TIMEOUT or dropped during FIRE → immediate concession
                    opponent = 2 if current_player == 1 else 1
                    self._conclude(opponent, reason="timeout")
                    return

                if coord == "QUIT":
                    winner = 2 if current_player == 1 else 1
                    self._conclude(winner, reason="concession")
                    return

                row, col = coord  # tuple[int, int]
                # Prevent duplicate shots: check if this player already fired here
                key = (row, col)
                if key in self._fired[current_player]:
                    # Prevent duplicate shots: prompt error
                    self._notify(attacker_w, f"ERR Already fired at {self._coord_str(row, col)}, choose another")
                    continue  # re-prompt same player
                self._fired[current_player].add(key)

                # Peek ship letter before firing to identify which ship was hit (server console only)
                orig_cell = defender_board.hidden_grid[row][col]
                result, sunk_name = defender_board.fire_at(row, col)
                coord_txt = self._coord_str(row, col)

                # --- Human-friendly descriptive messages (single source of truth for clients/bots) ---
                if result == "hit":
                    attacker_msg = f"YOU HIT at {coord_txt}"
                    defender_msg = f"OPPONENT HIT your ship at {coord_txt}"
                    if sunk_name:
                        attacker_msg = f"YOU SUNK opponent's {sunk_name} at {coord_txt}"
                        defender_msg = f"OPPONENT SUNK your {sunk_name} at {coord_txt}"
                else:  # miss
                    attacker_msg = f"YOU MISSED at {coord_txt}"
                    defender_msg = f"OPPONENT MISSED at {coord_txt}"

                io_send(attacker_w, self.io_seq, msg=attacker_msg); self.io_seq += 1
                io_send(defender_w, self.io_seq, msg=defender_msg); self.io_seq += 1
                # Send per-shot messages to all spectators via hub
                self.spec.broadcast(attacker_msg)
                self.spec.broadcast(defender_msg)

                # Count valid shot (hit or miss)
                if result in {"hit", "miss"}:
                    self._shots[current_player] += 1

                    # Emit structured shot event for server routing
                    self._emit(
                        Event(
                            Category.TURN,
                            "shot",
                            {
                                "attacker": current_player,
                                "coord": coord_txt,
                                "result": result,
                                "sunk": sunk_name or "",
                            },
                        )
                    )

                # Check game-over
                if defender_board.all_ships_sunk():
                    self._conclude(current_player, reason="fleet destroyed")
                    return

                # After each turn send updated own-board views to both players
                ok1 = send_grid(self.p1_file_w, self.io_seq, self.board_p1, reveal=True); self.io_seq += 1
                ok2 = send_grid(self.p2_file_w, self.io_seq, self.board_p2, reveal=True); self.io_seq += 1
                if not ok1 or not ok2:
                    winner = 2 if not ok1 else 1
                    self._conclude(winner, reason="timeout/disconnect")
                    return

                # Also send updated opponent views immediately
                send_grid(self.p1_file_w, self.io_seq, self.board_p2); self.io_seq += 1
                send_grid(self.p2_file_w, self.io_seq, self.board_p1); self.io_seq += 1

                # After each turn, check for disconnects on the non-turn player
                non_turn_player = 2 if current_player == 1 else 1
                non_turn_r, non_turn_w = self._file_pair(non_turn_player)
                try:
                    # Use select to poll for data with a short timeout
                    sock = non_turn_r.buffer.raw._sock
                    poll_delay = _cfg.SERVER_POLL_DELAY
                    readable, _, _ = select.select([sock], [], [], poll_delay)
                    if readable:
                        line = safe_readline(non_turn_r, lambda: self.recon.wait(non_turn_player))
                        if not line:
                            print(f"[DEBUG] run: disconnect detected on player {non_turn_player} after turn (readline)")
                            # allow reconnect first
                            if self.recon.wait(non_turn_player):
                                # Original player rejoined: rebind socket
                                new_sock = self.recon.take_new_socket(non_turn_player)
                                self._rebind_slot(non_turn_player, new_sock)
                                continue  # resume turn with reattached player
                            # Try to promote a spectator into the vacant slot
                            if self.spec.promote(non_turn_player, self):
                                continue  # resume this turn with the new player
                            # No one left to promote → end the game
                            self._conclude(current_player, reason="timeout/disconnect")
                            return
                        # Ignore extra data read during poll – next turn will handle.
                except Exception:
                    pass

                # After every *two* half-turns broadcast a fresh dual-board to spectators
                self._half_turn_counter += 1
                if self._half_turn_counter % 2 == 0:
                    self.spec.snapshot(self.board_p1, self.board_p2)

                # Next player's turn
                current_player = 2 if current_player == 1 else 1
        finally:
            # One last board snapshot for any connected spectators.
            self.spec.snapshot(self.board_p1, self.board_p2)
            # Cleanup reconnect tokens
            from .server import PID_REGISTRY
            PID_REGISTRY.pop(self.recon.token1, None)
            PID_REGISTRY.pop(self.recon.token2, None)

    # -------------------- internal utilities --------------------
    def _rebind_slot(self, slot: int, sock: socket.socket) -> None:
        """Rebind player slot to a new socket after reconnect."""
        if slot == 1:
            self.p1_sock = sock
            self.p1_file_r = sock.makefile("r")
            self.p1_file_w = sock.makefile("w")
        else:
            self.p2_sock = sock
            self.p2_file_r = sock.makefile("r")
            self.p2_file_w = sock.makefile("w")
        # Notify session ready if needed

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
        def_sock: socket.socket = defender_r.buffer.raw._sock

        while True:
            remaining = TURN_TIMEOUT - (time.time() - start)
            if remaining <= 0:
                print("[DEBUG] _receive_coord: turn timeout")
                return None
            # Wait until either socket has data or timeout expires
            readable, _, _ = select.select([att_sock, def_sock], [], [], remaining)
            if not readable:
                print("[DEBUG] _receive_coord: select timeout")
                return None  # timeout

            for sock in readable:
                # Determine which input stream and player slot
                file = r if sock is att_sock else defender_r
                slot = 1 if file is self.p1_file_r else 2
                # Perform a safe read with reconnect logic
                line = safe_readline(file, lambda: self.recon.wait(slot))
                if not line:
                    # Treat empty as disconnect
                    if file is defender_r:
                        print("[DEBUG] _receive_coord: disconnect detected on defender socket")
                        return "DEFENDER_LEFT"
                    print("[DEBUG] _receive_coord: disconnect detected on attacker socket")
                    return None
                line = line.strip()
                upper = line.upper()

                if sock is def_sock:
                    # Defender is not on turn
                    if upper.startswith("CHAT "):
                        chat_txt = line[5:].strip()
                        idx = 2 if file is defender_r else 1
                        chat_payload = {"name": f"P{idx}", "msg": chat_txt}
                        io_send(self.p1_file_w, self.io_seq, ptype=PacketType.CHAT, msg=f"[CHAT] P{idx}: {chat_txt}", obj=chat_payload); self.io_seq += 1
                        io_send(self.p2_file_w, self.io_seq, ptype=PacketType.CHAT, msg=f"[CHAT] P{idx}: {chat_txt}", obj=chat_payload); self.io_seq += 1
                        self._emit(Event(Category.CHAT, "line", {"player": idx, "msg": chat_txt}))
                        continue
                    elif upper == "QUIT":
                        winner = 1 if file is defender_r else 2
                        self._conclude(winner, reason="concession")
                        return None
                    elif upper.startswith("FIRE "):
                        io_send(defender_w, self.io_seq, msg="ERR Not your turn – wait for your turn prompt"); self.io_seq += 1
                        continue  # keep waiting for attacker
                    else:
                        io_send(defender_w, self.io_seq, msg="ERR Invalid command. Use: FIRE <A-J1-10> or QUIT"); self.io_seq += 1
                        continue
                else:  # Attacker's own input
                    if upper.startswith("CHAT "):
                        chat_txt = line[5:].strip()
                        idx = 1 if file is self.p1_file_r else 2
                        chat_payload = {"name": f"P{idx}", "msg": chat_txt}
                        io_send(self.p1_file_w, self.io_seq, ptype=PacketType.CHAT, msg=f"[CHAT] P{idx}: {chat_txt}", obj=chat_payload); self.io_seq += 1
                        io_send(self.p2_file_w, self.io_seq, ptype=PacketType.CHAT, msg=f"[CHAT] P{idx}: {chat_txt}", obj=chat_payload); self.io_seq += 1
                        self._emit(Event(Category.CHAT, "line", {"player": idx, "msg": chat_txt}))
                        continue
                    if upper == "QUIT":
                        return "QUIT"
                    if upper.startswith("FIRE "):
                        coord_str = line[5:].strip().upper()
                        if COORD_RE.match(coord_str):
                            row = ord(coord_str[0]) - ord('A')
                            col = int(coord_str[1:]) - 1
                            return (row, col)
                        io_send(w, self.io_seq, msg="ERR Invalid coordinate. Example: FIRE B7"); self.io_seq += 1

    def _conclude(self, winner: int, *, reason: str) -> None:
        print(f"[DEBUG] _conclude: winner={winner}, reason={reason}")
        loser = 2 if winner == 1 else 1
        win_w = self.p1_file_w if winner == 1 else self.p2_file_w
        lose_w = self.p2_file_w if winner == 1 else self.p1_file_w
        shots = self._shots.get(winner, 0)
        self._notify(win_w, f"YOU HAVE WON WITH {shots} SHOTS")
        self._notify(lose_w, f"YOU HAVE LOST – opponent won with {shots} shots")

        # Record result for server logs
        self.winner = winner
        self.win_reason = reason
        self.win_shots = shots  # type: ignore[attr-defined]
        # Spectators no longer receive free-text finale; emit line to server logs only.
        result_line = f"[GAME] Match finished – P{winner} wins by {reason} in {shots} shots."
        print(result_line)

        # Emit end-of-game event
        self._emit(Event(Category.TURN, "end", {"winner": winner, "reason": reason, "shots": shots}))
        # Send structured end-of-game frames to clients so bots can handle WIN/LOSE
        end_payload = {"type": "end", "winner": winner, "shots": shots}
        io_send(win_w, self.io_seq, obj=end_payload); self.io_seq += 1
        io_send(lose_w, self.io_seq, obj=end_payload); self.io_seq += 1

    @staticmethod
    def _coord_str(row: int, col: int) -> str:  # Helper for "HIT B5"
        return f"{chr(ord('A') + row)}{col + 1}"

    # Spectator operations delegated to SpectatorHub

    # -------------------- event bus --------------------
    def subscribe(self, cb: Callable[[Event], None]) -> None:
        """Allow external components (server/logger) to receive game events."""
        self._subs.append(cb)

    def _emit(self, ev: Event) -> None:
        for cb in tuple(self._subs):
            try:
                cb(ev)
            except Exception:
                # Don't let a misbehaving subscriber kill the game thread
                pass

# End of GameSession module
# EOF

