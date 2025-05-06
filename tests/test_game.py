"""Unit tests for the core Battleship game logic."""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

# Ensure local `src` directory is importable before project is installed.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from beer.battleship import Board, parse_coordinate


def test_parse_coordinate_basic() -> None:
    """Ensure coordinates convert as expected."""
    assert parse_coordinate("A1") == (0, 0)
    assert parse_coordinate("C10") == (2, 9)


@pytest.mark.parametrize(
    "coord",
    [
        "A1",
        "B3",
        "J10",
    ],
)
def test_fire_at_any_coord(coord: str) -> None:
    """Firing at any valid coordinate should yield a sensible result."""
    board = Board()
    board.place_ships_randomly()
    row, col = parse_coordinate(coord)
    result, _ = board.fire_at(row, col)
    assert result in {"hit", "miss"}


def test_all_ships_sunk() -> None:
    board = Board()
    board.place_ships_randomly()

    # Brute-force fire at every cell to guarantee victory.
    for r in range(board.size):
        for c in range(board.size):
            board.fire_at(r, c)
    assert board.all_ships_sunk()
