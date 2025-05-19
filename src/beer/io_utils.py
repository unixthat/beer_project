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
from .common import PacketType, send_pkt, recv_pkt
from .battleship import Board
from .commands import parse_command, ChatCommand, FireCommand, QuitCommand, CommandParseError
import socket
from .encryption import get_rekey_pub
import logging

logger = logging.getLogger("beer.io_utils")


def send(
    w: TextIO, seq: int, ptype: PacketType = PacketType.GAME, *, msg: str | None = None, obj: Any | None = None
) -> bool:
    # Debug print of send parameters
    logger.debug("send() start – ptype=%s seq=%d msg=%r obj=%r", ptype, seq, msg, obj)
    payload = obj if obj is not None else {"msg": msg}
    # Attempt to detect EOF on underlying socket, if available
    sock = None
    try:
        # type: ignore[attr-defined]
        sock = w.buffer.raw._sock
    except Exception:
        sock = None
    if sock:
        # non-blocking peek to detect closed peer
        try:
            data = sock.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            if len(data) == 0:
                # peer closed connection
                return False
        except BlockingIOError:
            # no data available, assume connection is alive
            pass
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # peer reset/closed
            return False
        except OSError:
            # e.g. socket not connected; skip EOF check
            pass
    try:
        send_pkt(w.buffer, ptype, seq, payload)  # type: ignore[arg-type]
        w.buffer.flush()
        logger.debug("send() success – ptype=%s seq=%d", ptype, seq)
        return True
    except (BrokenPipeError, ConnectionResetError):
        # peer closed or reset during send
        return False
    except Exception as e:
        logger.exception("send() failed – seq=%d ptype=%s", seq, ptype)
        return False


def grid_rows(board: Board, *, reveal: bool = False) -> List[str]:
    logger.debug("grid_rows() start – reveal=%s", reveal)
    rows: list[str] = []
    for r in range(board.size):
        cell_row = [board.hidden_grid[r][c] if reveal else board.display_grid[r][c] for c in range(board.size)]
        rows.append(" ".join(cell_row))
    logger.debug("grid_rows() result – rows_count=%d", len(rows))
    return rows


def send_grid(w: TextIO, seq: int, board: Board, *, reveal: bool = False) -> bool:
    logger.debug("send_grid() – seq=%d reveal=%s", seq, reveal)
    return send(w, seq, PacketType.GAME, obj={"type": "grid", "rows": grid_rows(board, reveal=reveal)})


def send_opp_grid(w: TextIO, seq: int, board: Board) -> bool:
    """Reveal the _opponent_ ship map (hidden_grid) to a client."""
    logger.debug("send_opp_grid() – seq=%d reveal_opponent", seq)
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
        except UnicodeDecodeError:
            # skip binary frame data silently
            continue
        except (OSError, ConnectionResetError) as e:
            logger.debug("safe_readline() error – %s", e)
            line = ""
        if line:
            logger.debug("safe_readline() got line %r", line)
            return line
        if attempts == 0 and on_disconnect():
            logger.debug("safe_readline() reconnect attempt")
            attempts += 1
            continue
        logger.debug("safe_readline() returning empty line")
        return ""


def chat_broadcast(writers: list[TextIO], seq: int, idx: int, chat_txt: str, payload: Any) -> int:
    logger.debug("chat_broadcast() – idx=%d chat_txt=%r", idx, chat_txt)
    for w in writers:
        send(w, seq, PacketType.CHAT, msg=f"[CHAT] P{idx}: {chat_txt}", obj=payload)
        seq += 1
    # Rekey handshake if pending
    pub = get_rekey_pub()
    if pub is not None:
        for w in writers:
            send(w, seq, PacketType.REKEY, obj=pub.hex())
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
    # Debug: entry into recv_turn
    try:
        logger.debug("recv_turn start – attacker_sock=%r defender_sock=%r", r.buffer.raw._sock, defender_r.buffer.raw._sock)
    except Exception:
        logger.debug("recv_turn start – could not access raw sockets for debug")
    start = _time.time()
    while True:
        att_sock = r.buffer.raw._sock
        def_sock = defender_r.buffer.raw._sock
        remaining = TURN_TIMEOUT - (_time.time() - start)
        logger.debug("recv_turn timer – remaining timeout=%.3f seconds", remaining)
        if remaining <= 0:
            return None

        # Only block on the attacker socket
        readable, _, _ = _select.select([att_sock], [], [], remaining)
        logger.debug("recv_turn select – readable=%r", readable)
        if not readable:
            return None

        # Process attacker input
        file = r
        writer = w
        try:
            logger.debug("recv_turn() – only waiting on attacker socket")
            while True:
                ptype2, seq2, obj = recv_pkt(file.buffer)
                logger.debug("recv_turn frame – ptype=%s seq=%d obj=%r", ptype2, seq2, obj)
                # Skip non-GAME packets
                if ptype2 != PacketType.GAME:
                    logger.debug("recv_turn skip non-GAME packet ptype=%s seq=%d", ptype2, seq2)
                    continue
                if isinstance(obj, dict):
                    line = obj.get("msg", "")
                else:
                    line = obj or ""
                logger.debug("recv_turn() framed line – %r", line)
                ul = line.strip().upper()
                if ul.startswith("FIRE ") or ul == "QUIT":
                    cmd = parse_command(line)
                    logger.debug("recv_turn parsed command – %r", cmd)
                    if isinstance(cmd, QuitCommand):
                        logger.debug("recv_turn returning QUIT")
                        return "QUIT"
                    if isinstance(cmd, FireCommand):
                        logger.debug("recv_turn returning FIRE at (%d,%d)", cmd.row, cmd.col)
                        return (cmd.row, cmd.col)
                elif ul.startswith("CHAT "):
                    cmd = parse_command(line)
                    sender = session.current or 1
                    name = f"P{sender}"
                    session.io_seq = chat_broadcast(
                        [session.p1_file_w, session.p2_file_w],
                        session.io_seq,
                        sender,
                        cmd.text,
                        {"name": name, "msg": cmd.text},
                    )
                    session._broadcast(None, {"type": "chat", "name": name, "msg": cmd.text})
                    continue
                else:
                    send(writer, session.io_seq, msg="ERR Invalid command. Use: FIRE <A-J1-10> or QUIT")
                    session.io_seq += 1
                    continue
        except CommandParseError as e:
            send(writer, session.io_seq, msg=f"ERR {e}")
            session.io_seq += 1
            continue
        except Exception:
            continue

        # Non-blocking check for defender chat (out-of-turn)
        try:
            readable_def, _, _ = _select.select([def_sock], [], [], 0)
            if def_sock in readable_def:
                ptype3, seq3, obj3 = recv_pkt(defender_r.buffer)
                if ptype3 == PacketType.GAME and isinstance(obj3, dict):
                    line3 = obj3.get("msg", "")
                    ul3 = line3.strip().upper()
                    if ul3.startswith("CHAT "):
                        cmd3 = parse_command(line3)
                        sender3 = 2 if session.current == 1 else 1
                        name3 = f"P{sender3}"
                        session.io_seq = chat_broadcast(
                            [session.p1_file_w, session.p2_file_w],
                            session.io_seq,
                            sender3,
                            cmd3.text,
                            {"name": name3, "msg": cmd3.text},
                        )
                        session._broadcast(None, {"type": "chat", "name": name3, "msg": cmd3.text})
        except Exception:
            pass


def refresh_views(
    w1: TextIO,
    w2: TextIO,
    seq: int,
    board1: Board,
    board2: Board,
) -> Tuple[bool, bool, int]:
    logger.debug("refresh_views() start – seq=%d", seq)
    ok1 = send_grid(w1, seq, board1, reveal=True)
    seq += 1
    ok2 = send_grid(w2, seq, board2, reveal=True)
    seq += 1
    send_grid(w1, seq, board2)
    seq += 1
    send_grid(w2, seq, board1)
    seq += 1
    logger.debug("refresh_views() done – seq=%d", seq)
    return ok1, ok2, seq
