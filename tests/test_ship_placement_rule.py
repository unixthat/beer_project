import pytest

from beer.battleship import Board, SHIPS


def test_cannot_place_orthogonally_adjacent_ships():
    """Ensure Board.can_place_ship() blocks placements that touch other ships orthogonally.

    Manual placement relies on can_place_ship() to validate the coordinates before
    mutating the board via do_place_ship().  The rule states that two ships may
    *not* share an edge (orthogonal adjacency).  This test places an initial ship
    and then tries to place another ship immediately adjacent on each of the four
    sides, asserting that every attempt is rejected.
    """
    board = Board()

    # Pre-place a three-long ship horizontally starting at (4, 4).
    row, col = 4, 4
    ship_size = 3
    horizontal = 0  # orientation constant in the package

    assert board.can_place_ship(row, col, ship_size, horizontal)
    board.do_place_ship(row, col, ship_size, horizontal, "C")

    # All cells that are orthogonally adjacent to the occupied squares
    adjacent_coords = [
        (row - 1, col),        # above first cell
        (row + 1, col),        # below first cell
        (row, col - 1),        # left of first cell
        (row, col + ship_size) # right of last cell
    ]

    second_ship_size = 2
    for r, c in adjacent_coords:
        # Skip coordinates that fall off the board (edge cases)
        if not (0 <= r < board.size and 0 <= c < board.size):
            continue
        allowed = board.can_place_ship(r, c, second_ship_size, horizontal)
        assert not allowed, (
            f"Ship placement at {(r, c)} should be rejected because it touches "
            "another ship orthogonally, but can_place_ship() returned True."
        )
