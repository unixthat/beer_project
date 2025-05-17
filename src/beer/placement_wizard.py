# placement_wizard.py
"""
Interactive manual-placement helper.
Usage:
    ok = run(board, reader, writer, safe_read)
Returns True when all ships placed, False on disconnect / abort.
"""

from typing import TextIO, Callable
from .battleship import SHIPS, parse_coordinate, SHIP_LETTERS
from .io_utils import send_grid

import re

COORD_RE = re.compile(r"^[A-J](10|[1-9])$")  # same as in session.py


def run(board, r: TextIO, w: TextIO, safe_read: Callable[[TextIO], str]) -> bool:
    # Ask preference
    w.write("INFO Manual placement? [y/N]\n"); w.flush()
    pref = safe_read(r).strip().upper()
    if not pref.startswith("Y"):
        return True  # keep random placement

    # Clear board
    board.reset()

    for ship_name, ship_size in SHIPS:
        while True:
            send_grid(w, 0, board, reveal=True)
            w.write(f"INFO Place {ship_name} – <coord> [H|V]\n"); w.flush()
            line = safe_read(r)
            if not line:
                return False  # lost connection
            parts = line.strip().upper().split()
            if len(parts) != 2:
                w.write("ERR Syntax: e.g. A1 H\n"); w.flush(); continue
            coord_str, orient_str = parts
            if not COORD_RE.match(coord_str):
                w.write("ERR Invalid coordinate\n"); w.flush(); continue
            row, col = parse_coordinate(coord_str)
            orientation = 0 if orient_str == "H" else 1 if orient_str == "V" else None
            if orientation is None:
                w.write("ERR Orientation must be H or V\n"); w.flush(); continue
            if not board.place_ship_safe(row, col, ship_size, orientation, SHIP_LETTERS[ship_name]):
                w.write("ERR Overlap / out-of-bounds\n"); w.flush(); continue
            break

    send_grid(w, 0, board, reveal=True)
    w.write("INFO All ships placed – waiting for opponent…\n"); w.flush()
    return True
