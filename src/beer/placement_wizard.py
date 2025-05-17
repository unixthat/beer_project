# placement_wizard.py
"""
Interactive manual-placement helper.
Usage:
    ok = run(board, reader, writer, safe_read)
Returns True when all ships placed, False on disconnect / abort.
"""

from typing import TextIO, Callable
from .battleship import Board, SHIPS, parse_coordinate, SHIP_LETTERS
from .io_utils import send as io_send, send_grid
from .coord_utils import COORD_RE
import time
from . import config as _cfg
import select

class PlacementTimeout(Exception):
    """Raised when manual ship placement exceeds the allowed time."""
    pass

def run(board: Board, r: TextIO, w: TextIO, safe_read: Callable[[TextIO], str]) -> bool:
    # Ask preference
    io_send(w, 0, msg="INFO Manual placement? [y/N]")
    # Wait up to PLACEMENT_TIMEOUT for the manual-placement answer
    sock = getattr(r.buffer.raw, '_sock', None)
    if sock is not None:
        readable, _, _ = select.select([sock], [], [], _cfg.PLACEMENT_TIMEOUT)
    else:
        readable = [True]
    if not readable:
        # No response in time: auto-decline manual placement
        board.place_ships_randomly()
        return True
    pref = safe_read(r).strip().upper()
    if not pref.startswith("Y"):
        # User declined manual placement -> perform automatic random placement
        board.place_ships_randomly()
        return True

    # Clear board
    board.reset()

    for ship_name, ship_size in SHIPS:
        # Reset timeout for each ship placement
        deadline = time.time() + _cfg.PLACEMENT_TIMEOUT
        while True:
            # Check remaining time
            remaining = deadline - time.time()
            if remaining <= 0:
                raise PlacementTimeout(f"Placement of {ship_name} timed out after {_cfg.PLACEMENT_TIMEOUT}s")
            send_grid(w, 0, board, reveal=True)
            io_send(w, 0, msg=f"INFO Place {ship_name} – <coord> [H|V]")
            line = safe_read(r)
            if not line:
                return False  # lost connection
            parts = line.strip().upper().split()
            if len(parts) != 2:
                io_send(w, 0, msg="ERR Syntax: e.g. A1 H")
                continue
            coord_str, orient_str = parts
            if not COORD_RE.match(coord_str):
                io_send(w, 0, msg="ERR Invalid coordinate")
                continue
            row, col = parse_coordinate(coord_str)
            orientation = 0 if orient_str == "H" else 1 if orient_str == "V" else None
            if orientation is None:
                io_send(w, 0, msg="ERR Orientation must be H or V")
                continue
            if not board.place_ship_safe(row, col, ship_size, orientation, SHIP_LETTERS[ship_name]):
                io_send(w, 0, msg="ERR Overlap / out-of-bounds")
                continue
            break

    send_grid(w, 0, board, reveal=True)
    io_send(w, 0, msg="INFO All ships placed – waiting for opponent…")
    return True
