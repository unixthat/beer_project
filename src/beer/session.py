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
from typing import TextIO, Any, Callable, List

from .battleship import Board, SHIPS, parse_coordinate, SHIP_LETTERS
from .common import PacketType, send_pkt, recv_pkt
from . import config as _cfg
from .events import Event, Category

COORD_RE = re.compile(r"^[A-J](10|[1-9])$")  # Valid 10×10 coords
TURN_TIMEOUT = _cfg.TURN_TIMEOUT  # seconds

# Global registry mapping reconnect tokens → ongoing GameSession
TOKEN_REGISTRY: dict[str, "GameSession"] = {}


class GameSession(threading.Thread):
    """Thread managing a single two-player match."""

    def __init__(self, p1: socket.socket, p2: socket.socket, *, ships=None, session_ready=None):
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
        # Registered spectator output streams (read-only clients)
        self.spectator_w_files: list[TextIO] = []
        # Every *half-turn* (i.e. after each individual shot) we increment
        # this counter; spectators receive a full dual-board update after
        # every *two* shots (both players have acted).
        self._half_turn_counter: int = 0
        self._lock = threading.Lock()
        self._seq = 0

        # Reconnect support (Tier 3)
        self.token_p1 = secrets.token_hex(4)
        self.token_p2 = secrets.token_hex(4)
        TOKEN_REGISTRY[self.token_p1] = self
        TOKEN_REGISTRY[self.token_p2] = self

        self._event_p1 = threading.Event()
        self._event_p2 = threading.Event()

        # Out-of-thread result reporting
        self.winner: int | None = None
        self.win_reason: str | None = None

        # Shot counters per player
        self._shots: dict[int, int] = {1: 0, 2: 0}

        # Event subscribers
        self._subs: List[Callable[[Event], None]] = []

        # Added for the new run method
        self._line_buffer: dict[int, str] = {}

    # -------------------- helpers --------------------
    def _send(
        self,
        w: TextIO,
        msg: str | None = None,
        ptype: PacketType = PacketType.GAME,
        obj: Any | None = None,
        *,
        mirror_spec: bool = False,
    ) -> bool:
        """Low-level helper that frames *payload* and writes it to *w*.

        Unlike the old implementation, **no automatic mirroring** to spectators
        happens here.  All spectator communication is funnelled through the
        dedicated `_send_spec_update()` helper so that we maintain *exactly*
        the information we want to expose.
        """
        payload = obj if obj is not None else {"msg": msg}
        seq = self._seq
        try:
            send_pkt(w.buffer, ptype, seq, payload)  # type: ignore[arg-type]
            w.buffer.flush()
        except Exception:
            return False
        # Spectator mirroring is now *explicit* via `_send_spec_update()` –
        # ignore the legacy `mirror_spec` flag (kept for call-site compatibility).
        self._seq += 1
        return True

    def _send_grid(self, w: TextIO, board: Board, *, reveal: bool = False) -> bool:
        """Send a grid view to *w*.

        Args:
            reveal: If True, ship letters are shown (used during manual placement).
        """
        rows = []
        for r in range(board.size):
            row_cells = []
            for c in range(board.size):
                if reveal:
                    cell = board.hidden_grid[r][c]
                    if cell == ".":
                        cell = "."
                else:
                    cell = board.display_grid[r][c]
                row_cells.append(cell)
            rows.append(" ".join(row_cells))

        grid_payload = {"type": "grid", "rows": rows}
        return self._send(w, "GRID", PacketType.GAME, grid_payload)

    # -------------------- gameplay --------------------
    def run(self) -> None:  # noqa: C901 complexity – fine for server thread
        """Main game-loop executed in its own thread until the match ends."""
        # sourcery skip: low-code-quality
        try:
            if self.session_ready:
                self.session_ready.set()  # Signal ready for spectators

            # Inform players of their order – P1 starts, include reconnect token
            self._emit(Event(Category.TURN, "start", {"token_p1": self.token_p1, "token_p2": self.token_p2}))
            # Legacy START frames (maintain compatibility during migration)
            self._send(self.p1_file_w, f"START you {self.token_p1}")
            self._send(self.p2_file_w, f"START opp {self.token_p2}")

            # ------------------ optional manual placement -------------------
            t1 = threading.Thread(target=self._handle_ship_placement, args=(1,))
            t2 = threading.Thread(target=self._handle_ship_placement, args=(2,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Initial own-fleet views to each player
            self._send_grid(self.p1_file_w, self.board_p1, reveal=True)
            self._send_grid(self.p2_file_w, self.board_p2, reveal=True)

            # Initial spectator snapshot (shot #0)
            self._send_spec_update()

            current_player = 1

            while True:
                # Poll both sockets for disconnect before each turn
                for idx, (r, w) in enumerate([(self.p1_file_r, self.p1_file_w), (self.p2_file_r, self.p2_file_w)], start=1):
                    sock = r.buffer.raw._sock
                    readable, _, _ = select.select([sock], [], [], 0)
                    if readable:
                        line = r.readline()
                        if not line:
                            print(f"[DEBUG] run: disconnect detected on player {idx} before turn")
                            winner = 2 if idx == 1 else 1
                            self._conclude(winner, reason="timeout/disconnect")
                            return
                        # Ignore any extra line data; disconnect already handled above.

                # Process buffered lines if any
                self._line_buffer.clear()

                attacker_r, attacker_w, defender_board, defender_name = self._select_players(current_player)
                # Identify defender streams for out-of-turn monitoring
                defender_idx = 2 if current_player == 1 else 1
                defender_r, defender_w = self._file_pair(defender_idx)

                # Send the attacker their current opponent grid view
                self._send_grid(attacker_w, defender_board)
                # Request coordinate (do NOT mirror to spectators)
                self._send(attacker_w, "INFO Your turn – FIRE <coord> or QUIT", mirror_spec=False)
                self._emit(Event(Category.TURN, "prompt", {"player": current_player}))

                coord = self._receive_coord(attacker_r, attacker_w, defender_r, defender_w)
                if coord == "DEFENDER_LEFT":
                    winner = 2 if current_player == 1 else 1
                    self._conclude(winner, reason="timeout/disconnect")
                    return
                if coord is None:
                    winner = 2 if current_player == 1 else 1
                    self._conclude(winner, reason="timeout/disconnect")
                    return

                if coord == "QUIT":
                    winner = 2 if current_player == 1 else 1
                    self._conclude(winner, reason="concession")
                    return

                row, col = coord  # tuple[int, int]
                # (Spectators no longer receive per-shot messages.)

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

                self._send(attacker_w, attacker_msg)
                self._send(defender_w, defender_msg)
                # Send per-shot messages to all spectators
                for wfile in list(self.spectator_w_files):
                    self._send(wfile, attacker_msg)
                    self._send(wfile, defender_msg)
                # (Spectators no longer receive per-shot HIT/MISS chatter.)

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
                ok1 = self._send_grid(self.p1_file_w, self.board_p1, reveal=True)
                ok2 = self._send_grid(self.p2_file_w, self.board_p2, reveal=True)
                if not ok1 or not ok2:
                    winner = 2 if not ok1 else 1
                    self._conclude(winner, reason="timeout/disconnect")
                    return

                # After each turn, check for disconnects on the non-turn player
                non_turn_player = 2 if current_player == 1 else 1
                non_turn_r, non_turn_w = self._file_pair(non_turn_player)
                try:
                    # Use select to poll for data with a short timeout
                    sock = non_turn_r.buffer.raw._sock
                    poll_delay = _cfg.SERVER_POLL_DELAY
                    readable, _, _ = select.select([sock], [], [], poll_delay)
                    if readable:
                        line = non_turn_r.readline()
                        if not line:
                            print(f"[DEBUG] run: disconnect detected on player {non_turn_player} after turn (readline)")
                            self._conclude(current_player, reason="timeout/disconnect")
                            return
                        # Ignore extra data read during poll – next turn will handle.
                except Exception:
                    pass

                # After every *two* half-turns broadcast a fresh dual-board to spectators
                self._half_turn_counter += 1
                if self._half_turn_counter % 2 == 0:
                    self._send_spec_update()

                # Next player's turn
                current_player = 2 if current_player == 1 else 1
        finally:
            # Always close sockets
            with self._lock:
                for sock in (self.p1_sock, self.p2_sock):
                    with contextlib.suppress(Exception):
                        sock.shutdown(socket.SHUT_RDWR)
                    sock.close()

            # One last board dump for any connected spectators.
            self._send_spec_update()

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
                file = r if sock is att_sock else defender_r
                try:
                    line = file.readline()
                except socket.timeout:
                    # No data despite select – continue polling
                    continue
                except OSError as ose:
                    # Timed-out or other socket error → treat as disconnect
                    print(f"[DEBUG] _receive_coord: OSError on {'attacker' if sock is att_sock else 'defender'} socket: {ose}")
                    return None if sock is att_sock else "DEFENDER_LEFT"
                if not line:  # disconnect
                    print(f"[DEBUG] _receive_coord: disconnect detected on {'attacker' if sock is att_sock else 'defender'} socket")
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
                        self._emit(Event(Category.CHAT, "line", {"player": idx, "msg": chat_txt}))
                        continue
                    elif upper == "QUIT":
                        winner = 1 if file is defender_r else 2
                        self._conclude(winner, reason="concession")
                        return None
                    elif upper.startswith("FIRE "):
                        self._send(defender_w, "ERR Not your turn – wait for your turn prompt")
                        continue  # keep waiting for attacker
                    else:
                        self._send(defender_w, "ERR Invalid command. Use: FIRE <A-J1-10> or QUIT")
                        continue
                else:  # Attacker's own input
                    if upper.startswith("CHAT "):
                        chat_txt = line[5:].strip()
                        idx = 1 if file is self.p1_file_r else 2
                        chat_payload = {"name": f"P{idx}", "msg": chat_txt}
                        self._send(self.p1_file_w, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
                        self._send(self.p2_file_w, f"[CHAT] P{idx}: {chat_txt}", PacketType.CHAT, chat_payload)
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
                        self._send(w, "ERR Invalid coordinate. Example: FIRE B7")

    def _conclude(self, winner: int, *, reason: str) -> None:
        print(f"[DEBUG] _conclude: winner={winner}, reason={reason}")
        loser = 2 if winner == 1 else 1
        win_w = self.p1_file_w if winner == 1 else self.p2_file_w
        lose_w = self.p2_file_w if winner == 1 else self.p1_file_w
        shots = self._shots.get(winner, 0)
        self._send(win_w, f"YOU HAVE WON WITH {shots} SHOTS", mirror_spec=False)
        self._send(lose_w, f"YOU HAVE LOST – opponent won with {shots} shots", mirror_spec=False)

        # Record result for server logs
        self.winner = winner
        self.win_reason = reason
        self.win_shots = shots  # type: ignore[attr-defined]
        # Spectators no longer receive free-text finale; emit line to server logs only.
        result_line = f"[GAME] Match finished – P{winner} wins by {reason} in {shots} shots."
        print(result_line)

        # Emit end-of-game event
        self._emit(Event(Category.TURN, "end", {"winner": winner, "reason": reason, "shots": shots}))

    @staticmethod
    def _coord_str(row: int, col: int) -> str:  # Helper for "HIT B5"
        return f"{chr(ord('A') + row)}{col + 1}"

    # ---------------- spectator API -----------------
    def add_spectator(self, sock: socket.socket) -> None:
        """Register an additional read-only client."""
        with self._lock:
            wfile = sock.makefile("w")
            self.spectator_w_files.append(wfile)
            # Welcome message – no mirroring so we avoid a duplicate.
            self._send(wfile, "YOU ARE SPECTATING")
            print("[DEBUG] Spectator attached", flush=True)  # Log for test harness
            self._emit(Event(Category.SYSTEM, "spectator_join", {}))

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

    # ------------------- setup phase --------------------
    def _handle_ship_placement(self, player_idx: int) -> None:
        """Interactively ask player whether to place ships manually and handle it."""
        r, w = self._file_pair(player_idx)
        opp_w = self.p2_file_w if player_idx == 1 else self.p1_file_w

        # Ask preference (no wait message to opponent)
        self._send(w, "INFO Manual placement? [Y/n]")

        # Temporarily set small timeout so tests/non-interactive clients proceed automatically
        sock_pref: socket.socket = r.buffer.raw._sock  # type: ignore[attr-defined]
        sock_pref.settimeout(_cfg.PLACEMENT_TIMEOUT)
        try:
            choice_line = r.readline()
        except Exception:
            choice_line = ""
        finally:
            sock_pref.settimeout(None)
        choice = choice_line.strip().upper() if choice_line else "N"

        if choice and choice.startswith("N"):
            return  # keep random placement already done in __init__

        # Replace randomly pre-populated board with a fresh empty one
        new_board = Board()
        if player_idx == 1:
            self.board_p1 = new_board
        else:
            self.board_p2 = new_board
        board = new_board

        for ship_name, ship_size in self.ships:
            while True:
                self._send_grid(w, board, reveal=True)
                self._send(w, f"INFO Place {ship_name} – <coord> [H|V]")
                try:
                    line = r.readline()
                except Exception:
                    return  # disconnect – handled later
                if not line:
                    return
                parts = line.strip().upper().split()
                if len(parts) != 2:
                    self._send(w, "ERR Syntax: e.g. A1 H")
                    continue
                coord_str, orient_str = parts
                if not COORD_RE.match(coord_str):
                    self._send(w, "ERR Invalid coordinate")
                    continue
                row, col = parse_coordinate(coord_str)
                orientation = 0 if orient_str == "H" else 1 if orient_str == "V" else None
                if orientation is None:
                    self._send(w, "ERR Orientation must be H or V")
                    continue
                # Try forward placement first; if out-of-bounds try opposite direction automatically
                if not board.can_place_ship(row, col, ship_size, orientation):
                    if orientation == 0:  # horizontal – try leftwards
                        adj_col = col - ship_size + 1
                        if adj_col >= 0 and board.can_place_ship(row, adj_col, ship_size, orientation):
                            col = adj_col
                        else:
                            self._send(w, "ERR Out-of-bounds or overlap")
                            continue
                    else:  # vertical – try upwards
                        adj_row = row - ship_size + 1
                        if adj_row >= 0 and board.can_place_ship(adj_row, col, ship_size, orientation):
                            row = adj_row
                        else:
                            self._send(w, "ERR Out-of-bounds or overlap")
                            continue
                # Place ship with unique letter
                board.do_place_ship(row, col, ship_size, orientation, SHIP_LETTERS[ship_name])
                break  # next ship

        self._send_grid(w, board, reveal=True)
        self._send(w, "INFO All ships placed – waiting for opponent…")

    # ---------------- spectator utilities -----------------

    def _grid_rows(self, board: Board) -> list[str]:
        """Return a *list[str]* representation of *board* with ships revealed."""
        rows: list[str] = []
        for r in range(board.size):
            row_cells = [board.hidden_grid[r][c] for c in range(board.size)]
            rows.append(" ".join(row_cells))
        return rows

    def _send_spec_update(self) -> None:
        """Send a *dual-board* snapshot to every connected spectator.

        The payload uses a dedicated `type:"spec_grid"` discriminator so that
        future spectator clients can render a bespoke view.  Both boards are
        sent **with ships revealed** so spectators can follow the full game
        progression.  Updates are emitted *once every two shots* (i.e. after
        each full round) plus an initial frame before the first turn.
        """
        # Send spec-grid to both players and any connected spectators
        recipients = [self.p1_file_w, self.p2_file_w] + list(self.spectator_w_files)
        if not recipients:
            return

        payload = {
            "type": "spec_grid",
            "rows_p1": self._grid_rows(self.board_p1),
            "rows_p2": self._grid_rows(self.board_p2),
        }
        for wfile in recipients:
            ok = self._send(wfile, ptype=PacketType.GAME, obj=payload)
            if wfile in self.spectator_w_files and not ok:
                # Drop dead spectator connections
                self.spectator_w_files.remove(wfile)

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

