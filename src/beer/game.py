"""Game utilities re-exporting core classes and functions for external import."""

from __future__ import annotations

from battleship import (
    Board,
    parse_coordinate,
    run_single_player_game_locally,
    run_single_player_game_online,
)

__all__ = [
    "Board",
    "parse_coordinate",
    "run_single_player_game_locally",
    "run_single_player_game_online",
]
