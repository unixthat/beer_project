# placement_wizard.py
"""
Interactive manual-placement helper over framing protocol.
Framing-based I/O usage:
    ok = run(board, recv_fn, notify, send_grid_fn)
Returns True when all ships placed, False on disconnect / abort.
"""

from typing import Callable
from .battleship import Board, SHIPS, parse_coordinate, SHIP_LETTERS
from .coord_utils import COORD_RE


class PlacementTimeout(Exception):
    """Raised when manual ship placement exceeds the allowed time."""

    pass


def run(
    board: Board,
    recv_fn: Callable[[], str],
    notify: Callable[[str], None],
    send_grid_fn: Callable[[Board, bool], None],
) -> bool:
    # Ask preference
    notify("INFO Manual placement? [y/N]")
    pref = recv_fn().strip().upper()
    if not pref.startswith("Y"):
        board.place_ships_randomly()
        return True

    # Clear board
    board.reset()

    for ship_name, ship_size in SHIPS:
        # Show current board
        send_grid_fn(board, reveal=True)
        notify(f"INFO Place {ship_name} – <coord> [H|V]")
        line = recv_fn()
        if not line:
            return False  # lost connection
        parts = line.strip().upper().split()
        if len(parts) != 2:
            notify("ERR Syntax: e.g. A1 H")
            continue
        coord_str, orient_str = parts
        if not COORD_RE.match(coord_str):
            notify("ERR Invalid coordinate")
            continue
        row, col = parse_coordinate(coord_str)
        orientation = 0 if orient_str == "H" else 1 if orient_str == "V" else None
        if orientation is None:
            notify("ERR Orientation must be H or V")
            continue
        if not board.place_ship_safe(row, col, ship_size, orientation, SHIP_LETTERS[ship_name]):
            notify("ERR Overlap / out-of-bounds")
            continue

    # Final board
    send_grid_fn(board, reveal=True)
    notify("INFO All ships placed – waiting for opponent…")
    return True
