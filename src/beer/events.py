"""Lightweight event model used by GameSession to decouple game logic from transport.

The goal is to emit strongly-typed events that the server can translate into
wire-protocol packets and other subscribers (e.g. logging or metrics) can
consume without parsing free-text strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, Callable


class Category(Enum):
    """High-level event categories."""

    TURN = auto()  # per-turn lifecycle (start, shot, end)
    CHAT = auto()  # player chat
    SYSTEM = auto()  # connect / disconnect / timeout etc.


@dataclass(slots=True)
class Event:
    """Immutable event emitted by GameSession."""

    category: Category
    type: str  # finer-grained identifier, e.g. "shot", "hit", "sunk"
    payload: Dict[str, Any]


class EventRouter:
    def __init__(self) -> None:
        self.handlers: Dict[str, Callable[[Event], None]] = {}

    def register_handler(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self.handlers[event_type] = handler

    def route_event(self, event: Event) -> None:
        if event.type in self.handlers:
            self.handlers[event.type](event)
        else:
            print(f"No handler for event type: {event.type}")       
