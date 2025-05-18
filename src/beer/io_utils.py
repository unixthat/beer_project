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
import socket


def send(
    w: TextIO, seq: int, ptype: PacketType = PacketType.GAME, *, msg: str | None = None, obj: Any | None = None
) -> bool:
    print(f"[DBG send] seq={seq} msg={msg} obj={obj}")
    payload = obj if obj is not None else {"msg": msg}
    try:
        send_pkt(w.buffer, ptype, seq, payload)  # type: ignore[arg-type]
        w.buffer.flush()
        print(f"[DBG send] success seq={seq}")
        return True
    except Exception as e:
        print(f"[DBG send] error seq={seq} error={e}")
        return False


def grid_rows(board: Board, *, reveal: bool = False) -> List[str]:
    print(f"[DBG grid_rows] reveal={reveal}")
    rows: list[str] = []
    for r in range(board.size):
        cell_row = [board.hidden_grid[r][c] if reveal else board.display_grid[r][c] for c in range(board.size)]
        rows.append(" ".join(cell_row))
    print(f"[DBG grid_rows] rows_count={len(rows)}")
    return rows


def send_grid(w: TextIO, seq: int, board: Board, *, reveal: bool = False) -> bool:
    print(f"[DBG send_grid] seq={seq} reveal={reveal}")
    return send(w, seq, PacketType.GAME, obj={"type": "grid", "rows": grid_rows(board, reveal=reveal)})


def send_opp_grid(w: TextIO, seq: int, board: Board) -> bool:
    """Reveal the _opponent_ ship map (hidden_grid) to a client."""
    print(f"[DBG send_opp_grid] seq={seq} reveal_opponent")
    return send(
        w,
        seq,
        PacketType.OPP_GRID,
        obj={"type": "opp_grid", "rows": grid_rows(board, reveal=True)},
    )


def safe_readline(
    reader: TextIO,
    on_disconnect: Callable[[], bool],
) -> str:
    attempts = 0
    while True:
        try:
            line = reader.readline()
        except (OSError, ConnectionResetError) as e:
            print(f"[DBG safe_readline] error {e}")
            line = ""
        if line:
            print(f"[DBG safe_readline] got line {line!r}")
            return line
        if attempts == 0 and on_disconnect():
            print(f"[DBG safe_readline] reconnect attempt")
            attempts += 1
            continue
        print("[DBG safe_readline] returning empty line")
        return ""


def chat_broadcast(writers: list[TextIO], seq: int, idx: int, chat_txt: str, payload: Any) -> int:
    print(f"[DBG chat_broadcast] idx={idx} chat_txt={chat_txt}")
    for w in writers:
        send(w, seq, PacketType.CHAT, msg=f"[CHAT] P{idx}: {chat_txt}", obj=payload)
        seq += 1
    return seq


def recv_turn(
    session,
    r: TextIO,
    w: TextIO,
    defender_r: TextIO,
    defender_w: TextIO,
) -> Any:
    import select as _select, time as _time

    # Debug prints removed; internal logic unchanged
    first_select = False

    start = _time.time()
    while True:
        att_sock = r.buffer.raw._sock  # type: ignore[attr-defined]
        def_sock = defender_r.buffer.raw._sock  # type: ignore[attr-defined]
        remaining = TURN_TIMEOUT - (_time.time() - start)
        if remaining <= 0:
            return None
        readable, _, _ = _select.select([att_sock, def_sock], [], [], remaining)
        if att_sock in readable and def_sock in readable:
            readable.sort(key=lambda s: 0 if s is att_sock else 1)
        if not readable:
            return None
        for sock in readable:
            file = r if sock is att_sock else defender_r
            writer = w if file is r else defender_w
            slot = 1 if file is session.p1_file_r else 2

            # ---- only the attacker socket ever "leaves" on empty/EOF ----
            if sock is att_sock and session._is_eof(sock):
                return "ATTACKER_LEFT"

            # Now there is actual data ready: read it
            try:
                raw_line = file.readline()
            except (OSError, ConnectionResetError):
                raw_line = ""
            if not raw_line:
                # only attacker empties are left events; defender just falls through
                if sock is att_sock:
                    return "ATTACKER_LEFT"
                continue

            line = raw_line.strip()
            try:
                cmd = parse_command(line)
            except CommandParseError as e:
                send(writer, session.io_seq, msg=f"ERR {e}")
                session.io_seq += 1
                continue
            if sock is def_sock:
                if isinstance(cmd, ChatCommand):
                    session.io_seq = chat_broadcast(
                        [session.p1_file_w, session.p2_file_w],
                        session.io_seq,
                        2,
                        cmd.text,
                        {"name": "P2", "msg": cmd.text},
                    )
                    continue
                if isinstance(cmd, QuitCommand):
                    session._conclude(1, reason="concession")
                    return None
                if isinstance(cmd, FireCommand):
                    send(defender_w, session.io_seq, msg="ERR Not your turn – wait for your turn prompt")
                    session.io_seq += 1
                    continue
                send(defender_w, session.io_seq, msg="ERR Invalid command. Use: FIRE <A-J1-10> or QUIT")
                session.io_seq += 1
                continue
            if isinstance(cmd, ChatCommand):
                session.io_seq = chat_broadcast(
                    [session.p1_file_w, session.p2_file_w], session.io_seq, 1, cmd.text, {"name": "P1", "msg": cmd.text}
                )
                continue
            if isinstance(cmd, QuitCommand):
                return "QUIT"
            if isinstance(cmd, FireCommand):
                return (cmd.row, cmd.col)
            # unknown command fallback
            send(w, session.io_seq, msg="ERR Unknown error processing command")
            session.io_seq += 1
            continue


def refresh_views(
    w1: TextIO,
    w2: TextIO,
    seq: int,
    board1: Board,
    board2: Board,
) -> Tuple[bool, bool, int]:
    print(f"[DBG refresh_views] seq={seq}")
    ok1 = send_grid(w1, seq, board1, reveal=True)
    seq += 1
    ok2 = send_grid(w2, seq, board2, reveal=True)
    seq += 1
    send_grid(w1, seq, board2)
    seq += 1
    send_grid(w2, seq, board1)
    seq += 1
    print(f"[DBG refresh_views] done seq={seq}")
    return ok1, ok2, seq
