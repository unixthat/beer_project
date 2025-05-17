import re
from typing import Tuple

# Regex for valid coordinates A1–J10
COORD_RE = re.compile(r"^[A-J](10|[1-9])$")

def coord_to_rowcol(coord: str) -> Tuple[int, int]:
    """
    Convert a coordinate like 'A1' through 'J10' to zero-based (row, col) tuple.
    """
    row = ord(coord[0]) - ord('A')
    col = int(coord[1:]) - 1
    return row, col


def format_coord(row: int, col: int) -> str:
    """
    Convert zero-based (row, col) to coordinate string like 'A1'.
    """
    return f"{chr(ord('A') + row)}{col + 1}"
