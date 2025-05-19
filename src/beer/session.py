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
import logging

from .battleship import Board, SHIPS, parse_coordinate, SHIP_LETTERS
from .common import PacketType, unpack, handle_control_frame
from .io_utils import (
    send as io_send,
    send_grid,
    send_opp_grid,
    chat_broadcast,
    recv_cmd,
    refresh_views,
    grid_rows,
)
from .commands import parse_command, ChatCommand, FireCommand, QuitCommand, CommandParseError
from .reconnect_controller import ReconnectController
from .placement_wizard import run as place_ships
from . import config as _cfg
from .events import Event, Category
from .coord_utils import coord_to_rowcol, format_coord, COORD_RE

TURN_TIMEOUT = _cfg.TURN_TIMEOUT  # seconds


class GameSession(threading.Thread):
    """Thread managing a single two-player match."""

    def __init__(
        self,
        p1: socket.socket,
        p2: socket.socket,
        *,
        token_p1: str,
        token_p2: str,
        ships=None,
        session_ready=None,
        broadcast: Callable[[str | None, Any | None], None],
    ):
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
        self._notify_player = lambda slot, txt: self._notify(self.p1_file_w if slot == 1 else self.p2_file_w, txt)
        # Broadcast callback for all waiting clients
        self._broadcast = broadcast

        # Initialize reconnect controller (registers both tokens)
        from .server import PID_REGISTRY
        self.recon = ReconnectController(
            TURN_TIMEOUT,
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
        self._fired: dict[int, set[tuple[int, int]]] = {1: set(), 2: set()}

        # Event subscribers
        self._subs: List[Callable[[Event], None]] = []

        # Added for the new run method
        self._line_buffer: dict[int, str] = {}
        # Keeps track of whose turn it is (1 or 2); set properly in run()
        self.current: int | None = None

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
        # Inform both players of their opponent's PID-token
        self._notify(self.p1_file_w, f"INFO You are now playing a new match against {self.token_p2}")
        self._notify(self.p2_file_w, f"INFO You are now playing a new match against {self.token_p1}")

        # Legacy START frames for compatibility
        self._notify(self.p1_file_w, f"START you {self.token_p1}")
        self._notify(self.p2_file_w, f"START opp {self.token_p2}")

        # Skip manual placement: randomly place ships for both players
        self.board_p1.place_ships_randomly()
        self.board_p2.place_ships_randomly()

        # Initial own-fleet reveal and opponent views for both players
        ok1, ok2, self.io_seq = refresh_views(
            self.p1_file_w,
            self.p2_file_w,
            self.io_seq,
            self.board_p1,
            self.board_p2,
        )
        # Reveal opponent hidden grid for cheat clients
        send_opp_grid(self.p1_file_w, self.io_seq, self.board_p2)
        self.io_seq += 1
        send_opp_grid(self.p2_file_w, self.io_seq, self.board_p1)
        self.io_seq += 1
        # Snapshot for any waiting clients
        rows_p1 = grid_rows(self.board_p1, reveal=True)
        rows_p2 = grid_rows(self.board_p2, reveal=True)
        self._broadcast(None, {"type": "spec_grid", "rows_p1": rows_p1, "rows_p2": rows_p2})

        # Signal ready for spectators
        if self.session_ready:
            self.session_ready.set()

    # -------------------- gameplay --------------------
    def run(self) -> None:  # noqa: C901 complexity – fine for server thread
        """Main game-loop executed in its own thread until the match ends."""
        try:
            # Handshake and placement
            self._begin_match()
            current_player = 1
            self.current = current_player

            while True:
                # Send turn prompt
                self._prompt_current_player()
                self._emit(Event(Category.TURN, "prompt", {"player": current_player}))

                # Receive next framed command, handling disconnects
                reader = self.p1_file_r.buffer if current_player == 1 else self.p2_file_r.buffer
                try:
                    cmd_line = recv_cmd(reader)
                except Exception:
                    # Attempt to handle disconnect and possible reconnect
                    if self._handle_disconnects([current_player]):
                        return
                    # Resume loop after successful reconnect
                    continue
                try:
                    cmd = parse_command(cmd_line)
                except CommandParseError as e:
                    # Invalid command: notify and re-prompt
                    w = self.p1_file_w if current_player == 1 else self.p2_file_w
                    self._notify(w, f"ERR {e}")
                    continue

                # Handle Quit
                if isinstance(cmd, QuitCommand):
                    logging.info(f"Player {current_player} conceded – ending match")
                    self.drop_and_deregister(current_player, reason="concession")
                    return

                # Handle Chat
                if isinstance(cmd, ChatCommand):
                    # Broadcast to the two players
                    self.io_seq = chat_broadcast(
                        [self.p1_file_w, self.p2_file_w],
                        self.io_seq,
                        current_player,
                        cmd.text,
                        {"name": f"P{current_player}", "msg": cmd.text},
                    )
                    # Also deliver as a CHAT frame to all spectators
                    self._broadcast(
                        None,
                        {"type": "chat", "name": f"P{current_player}", "msg": cmd.text},
                    )
                    # Server-side event routing
                    self._emit(Event(Category.CHAT, "line", {"player": current_player, "msg": cmd.text}))
                    continue

                # Handle Fire
                row, col = cmd.row, cmd.col
                # Prevent duplicate shots: check if this player already fired here
                key = (row, col)
                if key in self._fired[current_player]:
                    w = self.p1_file_w if current_player == 1 else self.p2_file_w
                    self._notify(w, f"ERR Already fired at {format_coord(row, col)}, choose another")
                    continue
                self._fired[current_player].add(key)
                # Resolve shot
                defender_board = self.board_p2 if current_player == 1 else self.board_p1
                defender_w = self.p2_file_w if current_player == 1 else self.p1_file_w
                attacker_w = self.p1_file_w if current_player == 1 else self.p2_file_w
                result, sunk_name = defender_board.fire_at(row, col)
                # Track shot count for winner stats
                self._shots[current_player] += 1

                coord_txt = format_coord(row, col)
                # Build messages
                if result == "hit":
                    attacker_msg = f"YOU HIT at {coord_txt}"
                    defender_msg = f"OPPONENT HIT your ship at {coord_txt}"
                else:
                    attacker_msg = f"YOU MISSED at {coord_txt}"
                    defender_msg = f"OPPONENT MISSED at {coord_txt}"
                # Send feedback
                io_send(attacker_w, self.io_seq, PacketType.GAME, msg=attacker_msg)
                self.io_seq += 1
                io_send(defender_w, self.io_seq, PacketType.GAME, msg=defender_msg)
                self.io_seq += 1
                # Report sunk ships
                if sunk_name:
                    io_send(attacker_w, self.io_seq, PacketType.GAME, msg=f"SUNK {sunk_name}")
                    self.io_seq += 1
                    io_send(defender_w, self.io_seq, PacketType.GAME, msg=f"SUNK {sunk_name}")
                    self.io_seq += 1

                # Event routing to spectators (shot events)
                self._broadcast(
                    {"player": current_player, "coord": coord_txt, "result": result, "sunk": sunk_name},
                    PacketType.GAME,
                )

                # Send updated boards to both players
                ok1, ok2, self.io_seq = refresh_views(
                    self.p1_file_w,
                    self.p2_file_w,
                    self.io_seq,
                    self.board_p1,
                    self.board_p2,
                )
                # Spectators get full dual-board every full turn (2 half-turns)
                self._half_turn_counter += 1
                if self._half_turn_counter % 2 == 0:
                    rows_p1 = grid_rows(self.board_p1, reveal=True)
                    rows_p2 = grid_rows(self.board_p2, reveal=True)
                    self._broadcast(
                        None,
                        {"type": "spec_grid", "rows_p1": rows_p1, "rows_p2": rows_p2},
                    )

                # Game over
                if defender_board.all_ships_sunk():
                    self._conclude(current_player, reason="fleet destroyed")
                    return

                # Next turn
                current_player = 2 if current_player == 1 else 1
                self.current = current_player
        finally:
            # One last board snapshot for any waiting clients
            rows_p1 = grid_rows(self.board_p1, reveal=True)
            rows_p2 = grid_rows(self.board_p2, reveal=True)
            self._broadcast(None, {"type": "spec_grid", "rows_p1": rows_p1, "rows_p2": rows_p2})
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

        # After rebinding, push the current boards to the re-attached player.
        self._sync_state(slot)
        # Don't prompt here; we'll get re-prompted in the next run() iteration

    # ------------------------------------------------------------
    # helper: push fresh boards to a just-reconnected player
    # ------------------------------------------------------------
    def _sync_state(self, slot: int) -> None:
        """
        Send up-to-date board state to a re-attaching client.

        • first – their own fleet reveal
        • second – opponent hidden grid (for cheats to re-seed)
        • third – opponent fog-of-war view
        """
        from .io_utils import send_grid, send_opp_grid  # ensure send_opp_grid is imported

        writer = self.p1_file_w if slot == 1 else self.p2_file_w
        own = self.board_p1 if slot == 1 else self.board_p2
        opp = self.board_p2 if slot == 1 else self.board_p1

        # 1) your own ships
        send_grid(writer, self.io_seq, own, reveal=True)
        self.io_seq += 1

        # 2) hidden opponent map for cheat clients
        send_opp_grid(writer, self.io_seq, opp)
        self.io_seq += 1

        # 3) fog-of-war view of opponent
        send_grid(writer, self.io_seq, opp, reveal=False)
        self.io_seq += 1

    def _select_players(self, current: int):
        if current == 1:
            return self.p1_file_r, self.p1_file_w, self.board_p2, "Player 2"
        return self.p2_file_r, self.p2_file_w, self.board_p1, "Player 1"

    def _file_pair(self, player_idx: int):
        return (self.p1_file_r, self.p1_file_w) if player_idx == 1 else (self.p2_file_r, self.p2_file_w)

    def _rebind_if_needed(self, slot: int) -> bool:
        """If a new socket has arrived for slot, swap to it and return True."""
        ok, sock = self.recon.try_rebind(slot)
        if ok:
            self._rebind_slot(slot, sock)
        return ok

    def _conclude(self, winner: int, *, reason: str) -> None:
        logging.debug(f"_conclude: winner={winner}, reason={reason}")
        loser = 2 if winner == 1 else 1
        win_w = self.p1_file_w if winner == 1 else self.p2_file_w
        lose_w = self.p2_file_w if winner == 1 else self.p1_file_w
        shots = self._shots.get(winner, 0)
        self._notify(win_w, f"YOU HAVE WON WITH {shots} SHOTS")
        self._notify(lose_w, f"YOU HAVE LOST – opponent won with {shots} shots")
        # If this was a concession, explicitly notify winner of opponent's forfeiture
        if reason == "concession":
            self._notify(win_w, "INFO Opponent has forfeited – match over")

        # Record result for server logs
        self.winner = winner
        self.win_reason = reason
        self.win_shots = shots  # type: ignore[attr-defined]
        # Spectators no longer receive free-text finale; emit line to server logs only.
        result_line = f"[GAME] Match finished – P{winner} wins by {reason} in {shots} shots."
        logging.info(result_line)

        # Emit end-of-game event (EventRouter will broadcast exactly one end-frame per client)
        self._emit(Event(Category.TURN, "end", {"winner": winner, "reason": reason, "shots": shots}))

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

    # Add helper for handling simultaneous disconnects
    def _handle_disconnects(self, dropped_slots: list[int]) -> bool:
        """
        Handle simultaneous disconnects: for each dropped slot, attempt reconnect,
        then spectator promotion; any that still fail are recorded. If any failures occur,
        conclude the match:
          - both fail: Player 1 wins by default, reason="abandoned"
          - single fail: opponent wins, reason="timeout/disconnect"
        Return True if the match concluded and run should exit, False otherwise.
        """
        for idx in dropped_slots:
            logging.info(f"Player {idx} disconnected – awaiting reconnect")
        failed: list[int] = []
        for idx in dropped_slots:
            if self.recon.wait(idx):
                logging.info(f"Player {idx} reconnected – resuming match")
                new_sock = self.recon.take_new_socket(idx)
                self._rebind_slot(idx, new_sock)
                continue
            # No recon and no in-session promotion → mark as failure
            failed.append(idx)
        if failed:
            if set(failed) == {1, 2}:
                winner = 1
                reason = "abandoned"
            else:
                winner = 2 if 1 in failed else 1
                reason = "timeout/disconnect"
            self._conclude(winner, reason=reason)
            return True
        return False

    def drop_and_deregister(self, slot: int, reason: str) -> None:
        """
        Close the given player's socket, unregister tokens, and conclude the match.
        """
        # Pick the loser's socket
        if slot == 1:
            sock = self.p1_sock
        else:
            sock = self.p2_sock

        # 1) Conclude the match while sockets are still open
        winner = 2 if slot == 1 else 1
        self._conclude(winner, reason=reason)

        # 2) Now shut down and close only the loser's socket
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        sock.close()

        # 3) Unregister reconnect tokens
        from .server import PID_REGISTRY

        PID_REGISTRY.pop(self.token_p1, None)
        PID_REGISTRY.pop(self.token_p2, None)

    # -----
    # Reconnect helpers (installed by cursor-fix-reconnect)
    # -----
    def _is_eof(self, sock: socket.socket) -> bool:
        """
        Return True only when the peer has really closed the TCP stream.
        Uses MSG_PEEK so no user data is consumed.
        """
        try:
            data = sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            return len(data) == 0
        except BlockingIOError:
            return False
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return True

    def _prompt_current_player(self) -> None:
        """
        Send the canonical 'Your turn' frame to whichever slot is stored in self.current.
        """
        w = self.p1_file_w if self.current == 1 else self.p2_file_w
        self._notify(w, "INFO YOUR TURN – FIRE <coord> or QUIT")

    # ------------------------------------------------------------
    def _control_loop(self, ctrl_reader, data_writer_buf):  # binary reader, BufferedWriter
        """Loop reading ACK/NAK control frames and invoke retransmit/prune."""
        from .common import PacketType
        while True:
            try:
                ptype, seq, obj = unpack(ctrl_reader)
            except Exception:
                break
            if ptype in (PacketType.ACK, PacketType.NAK):
                handle_control_frame(data_writer_buf, ptype, seq)


# End of GameSession module
# EOF
