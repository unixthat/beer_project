# io_utils.py
"""
Low-level helpers shared by GameSession and its sub-modules
–––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
• send()          – frame + flush arbitrary payloads
• send_grid()     – convenience wrapper for Board → grid packet
• safe_readline() – readline() with reconnect callback on EOF / socket error
• grid_rows()     – Board → ["A1 A2 …", …] helper (ships optionally revealed)
"""

from typing import Any, TextIO, Callable, List
from .common import PacketType, send_pkt
from .battleship import Board


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
