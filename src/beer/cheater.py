from collections import deque
import random
import time
from .battleship import BOARD_SIZE
from .battleship import SHIP_LETTERS


# Ship letters defined in battleship.SHIP_LETTERS
_SHIP_CHARS = set(SHIP_LETTERS.values())

# Only treat a grid as a "reveal" if it actually shows ships
def _is_reveal_grid(rows: list[str]) -> bool:
    """Return True if rows contain any ship letter."""
    for row in rows:
        for cell in row.split():
            if cell in _SHIP_CHARS:
                return True
    return False


class Cheater:
    """
    Tracks the defender's ship locations from the one reveal-grid
    packet the server gives you, then hands out exactly those coords.
    """

    def __init__(self, miss_rate: float = 0.0, delay: float = 0.5):
        self._targets = deque()
        self._seeded = False
        self._turn_ready = False
        self._last_rows: list[str] | None = None
        self._fired: set[str] = set()
        self.miss_rate = miss_rate
        self.delay = delay

    def feed_grid(self, rows: list[str]) -> None:
        """
        Seed your target queue whenever you receive a reveal-grid.
        The first time you see ships, or whenever you've emptied your old queue,
        this will clear and refill _targets for the new game.
        """
        # Always store the latest hidden-grid snapshot
        self._last_rows = rows

        if not _is_reveal_grid(rows):
            return

        # Only (re)seed when we haven't seeded yet, or have exhausted prior targets
        if not self._seeded or not self._targets:
            # Clear old targets (important between games)
            self._targets.clear()
            self._fired.clear()
            for r, line in enumerate(rows):
                for c, cell in enumerate(line.split()):
                    if cell in _SHIP_CHARS:
                        coord = f"{chr(ord('A') + r)}{c+1}"
                        self._targets.append(coord)
            self._seeded = True

    def notify_turn(self) -> None:
        """
        Called by the client when it receives the 'INFO Your turn' frame.
        Allows exactly one shot to be pulled from the queue.
        """
        self._turn_ready = True

    def next_shot(self) -> str | None:
        """Yield your next target, or None when you've exhausted the list."""
        # only fire when we've been signaled
        if not self._turn_ready:
            return None
        self._turn_ready = False

        # apply optional delay, interruptible
        try:
            if self.delay > 0:
                time.sleep(self.delay)
        except KeyboardInterrupt:
            return None

        # inject random misses based on miss_rate
        if self.miss_rate > 0 and random.random() < self.miss_rate:
            size = BOARD_SIZE
            while True:
                r = random.randrange(size)
                c = random.randrange(size)
                coord = f"{chr(ord('A') + r)}{c+1}"
                if coord not in self._fired:
                    self._fired.add(coord)
                    return coord

        # If we've run out but have a snapshot, re-seed
        if not self._targets and self._last_rows:
            # reset seed to allow re-fill
            self._seeded = False
            self.feed_grid(self._last_rows or [])
        if not self._targets:
            return None
        coord = self._targets.popleft()
        self._fired.add(coord)
        return coord
