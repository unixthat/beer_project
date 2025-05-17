import re
from dataclasses import dataclass
from typing import Union

from .coord_utils import COORD_RE, coord_to_rowcol


class CommandParseError(Exception):
    """Raised when a line cannot be parsed as a valid command."""


@dataclass(frozen=True)
class ChatCommand:
    text: str


@dataclass(frozen=True)
class FireCommand:
    row: int
    col: int


@dataclass(frozen=True)
class QuitCommand:
    pass


Command = Union[ChatCommand, FireCommand, QuitCommand]


def parse_command(line: str) -> Command:
    if line is None:
        raise CommandParseError("No command to parse")
    raw = line.strip()
    if not raw:
        raise CommandParseError("Empty command")
    parts = raw.split(maxsplit=1)
    verb = parts[0].upper()
    if verb == "CHAT":
        if len(parts) < 2 or not parts[1].strip():
            raise CommandParseError("CHAT requires a non-empty message")
        return ChatCommand(text=parts[1])
    elif verb == "FIRE":
        if len(parts) < 2 or not parts[1].strip():
            raise CommandParseError("FIRE requires a coordinate")
        coord = parts[1].strip().upper()
        if not COORD_RE.match(coord):
            raise CommandParseError(f"Invalid coordinate: {coord}")
        row, col = coord_to_rowcol(coord)
        return FireCommand(row=row, col=col)
    elif verb == "QUIT" and len(parts) == 1:
        return QuitCommand()
    else:
        raise CommandParseError(f"Unknown command: {raw}")
