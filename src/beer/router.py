"""Translate internal GameSession events into wire-protocol packets.

The router lives *outside* GameSession so that translation rules are declared
in a single place and can evolve without touching core game logic.  It is also
straight-forward to unit-test by feeding synthetic Event objects.
"""

from __future__ import annotations

import logging
from typing import Any

from .events import Event, Category
from .common import PacketType
from .io_utils import send as io_send
from .session import GameSession

logger = logging.getLogger(__name__)


class EventRouter:
    """Session-scoped helper that converts `Event` → `_send()` calls."""

    def __init__(self, session: "GameSession") -> None:  # noqa: F821 forward ref
        self._s = session

    # ------------------------------------------------------------------
    # Public dispatch entry
    # ------------------------------------------------------------------
    def __call__(self, ev: Event) -> None:  # GameSession calls router(event)
        try:
            self.dispatch(ev)
        except Exception:  # noqa: BLE001
            logger.exception("Event routing failed for %s", ev)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------
    def dispatch(self, ev: Event) -> None:  # noqa: C901 – few cases is fine
        cat = ev.category
        if cat is Category.TURN:
            self._handle_turn(ev)
        elif cat is Category.CHAT:
            self._handle_chat(ev)
        elif cat is Category.SYSTEM:
            self._handle_system(ev)
        else:  # pragma: no cover – unknown category
            logger.debug("Ignoring event %s", ev)

    # ------------------------------------------------------------------
    # Category handlers
    # ------------------------------------------------------------------
    def _handle_turn(self, ev: Event) -> None:
        t = ev.type
        if t == "shot":
            payload = {
                "type": "shot",
                "player": ev.payload["attacker"],
                "coord": ev.payload["coord"],
                "result": ev.payload["result"],
                "sunk": ev.payload["sunk"],
            }
            self._broadcast(payload, PacketType.GAME)
        elif t == "start":
            # No packet needed – legacy START frames already sent.
            pass
        elif t == "end":
            payload = {
                "type": "end",
                "winner": ev.payload["winner"],
                "reason": ev.payload["reason"],
                "shots": ev.payload["shots"],
            }
            self._broadcast(payload, PacketType.GAME)
        elif t == "prompt":
            payload = {"type": "turn_prompt", "player": ev.payload["player"]}
            self._unicast(ev.payload["player"], payload)
        else:
            logger.debug("Unhandled TURN event: %s", ev)

    def _handle_chat(self, ev: Event) -> None:
        if ev.type != "line":
            return
        # log chat on server; clients already get it directly from GameSession
        logger.info(f"\033[32m[CHAT] P{ev.payload['player']}: {ev.payload['msg']}\033[0m")

    def _handle_system(self, ev: Event) -> None:
        # Currently no dedicated SYSTEM packets.
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _broadcast(self, obj: Any, ptype: PacketType) -> None:
        s = self._s
        # Delegate to io_utils.send, preserving packet type and sequence
        io_send(s.p1_file_w, s.io_seq, ptype=ptype, obj=obj)
        s.io_seq += 1
        io_send(s.p2_file_w, s.io_seq, ptype=ptype, obj=obj)
        s.io_seq += 1
        # Spectators are handled automatically because GameSession mirrors
        # packets written to player streams.

    def _unicast(self, player_idx: int, obj: Any) -> None:
        s = self._s
        w = s.p1_file_w if player_idx == 1 else s.p2_file_w
        # Send only to specified player
        io_send(w, s.io_seq, ptype=PacketType.GAME, obj=obj)
        s.io_seq += 1
