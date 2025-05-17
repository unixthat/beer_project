# io_utils.py
"""
Low-level helpers shared by GameSession and its sub-modules
–––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
• send()          – frame + flush arbitrary payloads
• send_grid()     – convenience wrapper for Board → grid packet
• safe_readline() – readline() with reconnect callback on EOF / socket error
• grid_rows()     – Board → ["A1 A2 …", …] helper (ships optionally revealed)
"""

from typing import Any, TextIO, Callable, List, Tuple
from .config import TURN_TIMEOUT
from .common import PacketType, send_pkt
from .battleship import Board
from .commands import parse_command, ChatCommand, FireCommand, QuitCommand, CommandParseError


def send(w: TextIO, seq: int, ptype: PacketType = PacketType.GAME, *, msg: str | None = None, obj: Any | None = None) -> bool:
    payload = obj if obj is not None else {"msg": msg}
    try:
        send_pkt(w.buffer, ptype, seq, payload)  # type: ignore[arg-type]
        w.buffer.flush()
        return True
    except Exception:
        return False


def grid_rows(board: Board, *, reveal: bool = False) -> List[str]:
    rows: list[str] = []
    for r in range(board.size):
        cell_row = [
            board.hidden_grid[r][c] if reveal else board.display_grid[r][c]
            for c in range(board.size)
        ]
        rows.append(" ".join(cell_row))
    return rows


def send_grid(w: TextIO, seq: int, board: Board, *, reveal: bool = False) -> bool:
    # Always send grids as GAME packets
    return send(w, seq, PacketType.GAME, obj={"type": "grid", "rows": grid_rows(board, reveal=reveal)})


def safe_readline(
    r: TextIO,
    on_disconnect: Callable[[], bool],  # should return True on successful reconnect
    retry: bool = True,
) -> str:
    """
    Read one line; if EOF or socket error, invoke *on_disconnect* once.
    If that returns True, retry the read exactly once.
    """
    try:
        line = r.readline()
    except (OSError, ConnectionResetError):
        line = ""
    if line == "" and retry:
        if on_disconnect():
            # underlying reader has changed – call ourselves recursively once
            return safe_readline(r, on_disconnect, retry=False)
    return line


# Helper to broadcast chat messages to multiple clients
def chat_broadcast(writers: list[TextIO], seq: int, idx: int, chat_txt: str, payload: Any) -> int:
    """
    Broadcast a CHAT packet to each writer, incrementing seq.
    Returns updated seq after sending to all.
    """
    for w in writers:
        send(w, seq, PacketType.CHAT, msg=f"[CHAT] P{idx}: {chat_txt}", obj=payload)
        seq += 1
    return seq


# Helper to receive a turn: chat, FIRE, or QUIT with out-of-turn handling
def recv_turn(
    session,
    r: TextIO,
    w: TextIO,
    defender_r: TextIO,
    defender_w: TextIO,
) -> Any:
    """
    Wrapper for parsing client commands via commands.parse_command.
    Returns (row,col) for FIRE, "QUIT", None on timeout/disconnect, or "DEFENDER_LEFT".
    """
    import select as _select, time as _time

    start = _time.time()
    att_sock = r.buffer.raw._sock  # type: ignore[attr-defined]
    def_sock = defender_r.buffer.raw._sock  # type: ignore[attr-defined]
    while True:
        remaining = TURN_TIMEOUT - (_time.time() - start)
        if remaining <= 0:
            return None
        readable, _, _ = _select.select([att_sock, def_sock], [], [], remaining)
        if not readable:
            return None
        for sock in readable:
            file = r if sock is att_sock else defender_r
            writer = w if file is r else defender_w
            slot = 1 if file is session.p1_file_r else 2
            raw_line = safe_readline(file, lambda: session.recon.wait(slot))
            if not raw_line:
                if file is defender_r:
                    return "DEFENDER_LEFT"
                return None
            line = raw_line.strip()
            # Parse via commands.py
            try:
                cmd = parse_command(line)
            except CommandParseError as e:
                # Notify appropriate writer
                session.io_seq += 0  # ensure io_seq exists
                send(writer, session.io_seq, msg=f"ERR {e}")
                session.io_seq += 1
                continue

            # Defender sending out-of-turn
            if sock is def_sock:
                if isinstance(cmd, ChatCommand):
                    chat_txt = cmd.text
                    idx = 2
                    payload = {"name": f"P{idx}", "msg": chat_txt}
                    session.io_seq = chat_broadcast(
                        [session.p1_file_w, session.p2_file_w],
                        session.io_seq,
                        idx,
                        chat_txt,
                        payload,
                    )
                    session._emit(Event(Category.CHAT, "line", {"player": idx, "msg": chat_txt}))
                    continue
                if isinstance(cmd, QuitCommand):
                    winner = 1
                    session._conclude(winner, reason="concession")
                    return None
                if isinstance(cmd, FireCommand):
                    send(defender_w, session.io_seq, msg="ERR Not your turn – wait for your turn prompt")
                    session.io_seq += 1
                    continue
                # fallback
                send(defender_w, session.io_seq, msg="ERR Invalid command. Use: FIRE <A-J1-10> or QUIT")
                session.io_seq += 1
                continue

            # Attacker's turn
            if isinstance(cmd, ChatCommand):
                chat_txt = cmd.text
                idx = 1
                payload = {"name": f"P{idx}", "msg": chat_txt}
                session.io_seq = chat_broadcast(
                    [session.p1_file_w, session.p2_file_w],
                    session.io_seq,
                    idx,
                    chat_txt,
                    payload,
                )
                session._emit(Event(Category.CHAT, "line", {"player": idx, "msg": chat_txt}))
                continue
            if isinstance(cmd, QuitCommand):
                return "QUIT"
            if isinstance(cmd, FireCommand):
                return (cmd.row, cmd.col)
            # Should not reach here, but catch-all
            send(w, session.io_seq, msg="ERR Unknown error processing command")
                session.io_seq += 1
                continue


# Helper to refresh both players' boards with own and opponent views
def refresh_views(
    w1: TextIO,
    w2: TextIO,
    seq: int,
    board1: Board,
    board2: Board,
) -> Tuple[bool, bool, int]:
    """
    Send own-fleet reveal and opponent views to both players.
    Returns (ok1, ok2, new_seq).
    """
    ok1 = send_grid(w1, seq, board1, reveal=True); seq += 1
    ok2 = send_grid(w2, seq, board2, reveal=True); seq += 1
    # Opponent views
    send_grid(w1, seq, board2); seq += 1
    send_grid(w2, seq, board1); seq += 1
    return ok1, ok2, seq
