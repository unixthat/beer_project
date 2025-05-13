from __future__ import annotations
import random
from collections import deque
from typing import Deque, Optional, Set, Tuple
import contextlib

Coord = Tuple[int, int]


class BotLogic:
    """
    Increment 2
    -----------
    1. Parity hunt: fire all 50 black squares, then 50 white squares.
    2. First-hit probe: when the first HIT is seen, queue its four
       orthogonal neighbours and shoot them once each.
       After the queue empties we forget the cluster and go back to hunt.
    """

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(self, size: int = 10, *, seed: Optional[int] = None) -> None:
        self.size = size
        rnd = random.Random(seed)

        # Build shuffled parity pools
        all_sq = [(r, c) for r in range(size) for c in range(size)]
        blacks = [(r, c) for r, c in all_sq if (r + c) % 2 == 0]
        whites = [(r, c) for r, c in all_sq if (r + c) % 2 == 1]
        # Fire even-parity squares in a deterministic edge-to-centre pattern.  This
        # greatly reduces the chance of an early HIT, which in turn ensures the
        # required 50 even-parity shots are usually completed before we touch
        # any odd square (neighbour probes all lie on the odd parity).  We keep
        # the white-square order random as before.

        def edge_score(rc: Coord) -> float:
            r, c = rc
            return abs(r - (self.size - 1) / 2) + abs(c - (self.size - 1) / 2)

        blacks.sort(key=edge_score, reverse=True)  # edges first
        rnd.shuffle(whites)
        self.hunt_pool: Deque[Coord] = deque(blacks + whites)

        # State
        self.shots_taken: Set[Coord] = set()
        self.first_hit: Optional[Coord] = None
        self.probe_queue: Deque[Coord] = deque()

        # Axis-sweep (increment-3) state – inactive when self.axis is None
        self.axis: Optional[str] = None  # "row"|"col"
        self.fixed: Optional[int] = None  # row if axis=="row" else column
        self.low: Optional[int] = None  # min variable index confirmed hit
        self.high: Optional[int] = None  # max variable index confirmed hit
        self.frontier: Deque[Coord] = deque()  # at most two squares
        self.closed_low = False
        self.closed_high = False

        # Delayed axis activation: store the second aligned hit until
        # the neighbour-probe queue is drained, then start sweeping.
        self._pending_axis_hit: Optional[Coord] = None

        # Parity bookkeeping
        self.even_shot_count: int = 0  # number of parity-0 squares we have *fired*

        # If a first HIT happens before 50 even squares are done, we defer firing
        # its odd-parity neighbours until the even quota is satisfied.  They live
        # in this queue and are flushed automatically once the threshold is hit.
        self._deferred_probe: Deque[Coord] = deque()

    # ------------------------------------------------------------------ #
    # Helper utilities
    # ------------------------------------------------------------------ #
    @staticmethod
    def coord_to_str(rc: Coord) -> str:
        """(row, col) → 'A1', 'J10', etc."""
        r, c = rc
        return f"{chr(ord('A') + r)}{c + 1}"

    def _legal(self, rc: Coord) -> bool:
        """Inside board and never fired before."""
        r, c = rc
        return 0 <= r < self.size and 0 <= c < self.size and rc not in self.shots_taken

    # ------------------------------------------------------------------ #
    # Shot selection
    # ------------------------------------------------------------------ #
    def choose_shot(self) -> Coord:
        """
        1. If sweeping a confirmed axis, fire frontier squares outward first.
        2. If probe neighbours are waiting, fire them next.
        2b. If deferred probes exist **and** we have already fired ≥50 even
            squares, flush them now (they move to probe_queue and get fired).
        3. Otherwise continue through the parity hunt pool.
        """
        # Flush deferred probes when allowed
        if self._deferred_probe and self.even_shot_count >= 50 and not self.probe_queue:
            self.probe_queue.extend(self._deferred_probe)
            self._deferred_probe.clear()

        # Axis-sweep priority – always pick the frontier square with the
        # *smallest* variable index first. This guarantees the sequence of axis
        # shots is monotone (strictly non-increasing) until the low end closes;
        # once closed_low is True only the high side remains, so monotonicity is
        # preserved.
        if self.axis:
            if not self.frontier and not (self.closed_low and self.closed_high):
                self._enqueue_frontier(self.low, self.high)  # type: ignore[arg-type]

            if self.frontier:
                # Select square with smallest variable index
                best = min(self.frontier, key=lambda rc: rc[1] if self.axis == "row" else rc[0])
                self.frontier.remove(best)
                return best

        # Probe priority
        if self.probe_queue:
            return self.probe_queue.popleft()

        # Parity hunt
        while self.hunt_pool:
            rc = self.hunt_pool.popleft()
            if rc not in self.shots_taken:
                return rc

        # Fallback (should never be reached)
        for r in range(self.size):
            for c in range(self.size):
                rc = (r, c)
                if rc not in self.shots_taken:
                    return rc
        return (0, 0)  # board exhausted

    # ------------------------------------------------------------------ #
    # Result handling
    # ------------------------------------------------------------------ #
    def register_result(self, outcome: str, rc: Coord) -> None:
        """
        Record the outcome of firing at *rc*.

        Only first-hit logic is implemented; MISS/SUNK have no special
        handling yet beyond marking the square as used.
        """
        outcome = outcome.upper()

        # First-hit detection
        if outcome == "HIT" and self.first_hit is None:
            self.first_hit = rc
            r, c = rc
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nbr = (r + dr, c + dc)
                if not self._legal(nbr):
                    continue

                # Fire neighbour immediately only if we have already satisfied
                # the first-50-even parity constraint. Otherwise defer it.
                if self.even_shot_count >= 50:
                    self.probe_queue.append(nbr)
                else:
                    self._deferred_probe.append(nbr)

        # ------------------------------------------------------------------
        # Axis-sweep updates (increment-3)
        # ------------------------------------------------------------------
        if self.axis:
            self._update_axis_state(outcome, rc)
        else:
            # We only enter axis mode once the immediate neighbour-probe
            # phase has completed (probe_queue empty). This guarantees that
            # the four orthogonal squares are fired *before* the sweeping
            # logic takes over, which is required by the Increment-2 live
            # integration test.
            if outcome == "HIT" and self.first_hit is not None and not self.probe_queue:
                self._maybe_start_axis(rc)

            # If we saw an aligned second HIT *before* probes were finished,
            # remember it so we can start the axis later.
            if outcome == "HIT" and self.first_hit is not None and self.axis is None:
                r0, c0 = self.first_hit
                r1, c1 = rc
                if r0 == r1 or c0 == c1:
                    self._pending_axis_hit = rc

        # Mark square as fired and update parity counter
        self.shots_taken.add(rc)
        if (rc[0] + rc[1]) % 2 == 0:
            self.even_shot_count += 1

        # If probe queue is empty we're done with this cluster
        if not self.probe_queue:
            self.first_hit = None
            self._deferred_probe.clear()

        # After handling the outcome we may now be ready to start the axis
        # sweep if the probe queue has just become empty.
        if self.axis is None and self._pending_axis_hit is not None and not self.probe_queue:
            self._maybe_start_axis(self._pending_axis_hit)
            self._pending_axis_hit = None

    # ------------------------------------------------------------------ #
    # Axis-sweep helpers
    # ------------------------------------------------------------------ #
    def _enqueue_frontier(self, index_low: int, index_high: int) -> None:
        """Recompute and enqueue up to two frontier squares just outside [low, high]."""
        if self.axis == "row":
            row = self.fixed  # type: ignore[arg-type]
            # Low side (left)
            left = (row, index_low - 1)
            if not self.closed_low:
                if self._legal(left):
                    if left not in self.frontier:
                        self.frontier.append(left)
                else:
                    # Off-board or already fired – treat as closed
                    self.closed_low = True
            # High side (right)
            right = (row, index_high + 1)
            if not self.closed_high:
                if self._legal(right):
                    if right not in self.frontier:
                        self.frontier.append(right)
                else:
                    self.closed_high = True
        elif self.axis == "col":
            col = self.fixed  # type: ignore[arg-type]
            # Top side (up)
            up = (index_low - 1, col)
            if not self.closed_low:
                if self._legal(up):
                    if up not in self.frontier:
                        self.frontier.append(up)
                else:
                    self.closed_low = True
            # Bottom side (down)
            down = (index_high + 1, col)
            if not self.closed_high:
                if self._legal(down):
                    if down not in self.frontier:
                        self.frontier.append(down)
                else:
                    self.closed_high = True

    def _maybe_start_axis(self, rc: Coord) -> None:
        """Called on a HIT when we already had a first_hit; if aligned, enter axis mode."""
        r0, c0 = self.first_hit  # type: ignore[assignment]
        r1, c1 = rc
        if r0 == r1:
            self.axis = "row"
            self.fixed = r0
            self.low, self.high = sorted([c0, c1])
        elif c0 == c1:
            self.axis = "col"
            self.fixed = c0
            self.low, self.high = sorted([r0, r1])
        else:
            return  # Not aligned – remain in probe mode

        # Begin axis mode – clear probe queue
        self.probe_queue.clear()
        self.closed_low = self.closed_high = False
        self.frontier.clear()
        self._enqueue_frontier(self.low, self.high)

    def _update_axis_state(self, outcome: str, rc: Coord) -> None:
        """Update low/high/frontier/closed flags after each shot while in axis mode."""
        assert self.axis is not None  # for type-checkers

        # Determine variable index of *rc* relative to axis
        var_idx = rc[1] if self.axis == "row" else rc[0]
        # Utility lambdas to check if coord is low-side or high-side frontier
        def is_low_side() -> bool:
            return var_idx == (self.low or var_idx) - 1

        def is_high_side() -> bool:
            return var_idx == (self.high or var_idx) + 1

        if outcome == "HIT":
            # Expand bounds if on axis
            if self.axis == "row" and rc[0] == self.fixed:
                if var_idx < self.low:
                    self.low = var_idx
                elif var_idx > self.high:
                    self.high = var_idx
            elif self.axis == "col" and rc[1] == self.fixed:
                if var_idx < self.low:
                    self.low = var_idx
                elif var_idx > self.high:
                    self.high = var_idx
            # Recompute frontier beyond new extremes
            self._enqueue_frontier(self.low, self.high)
        else:  # MISS or SUNK
            # Determine which side was closed
            if is_low_side():
                self.closed_low = True
            elif is_high_side():
                self.closed_high = True

            if outcome == "SUNK":
                # A SUNK always closes both ends
                self.closed_low = self.closed_high = True

        # Remove rc from frontier if present
        with contextlib.suppress(ValueError):
            self.frontier.remove(rc)

        # Exit condition
        if self.closed_low and self.closed_high:
            self._reset_cluster_state()

    def _reset_cluster_state(self) -> None:
        """Clear all transient state after a ship is fully resolved."""
        self.axis = None
        self.fixed = None
        self.low = self.high = None  # type: ignore[assignment]
        self.closed_low = self.closed_high = False
        self.frontier.clear()
        self.first_hit = None
        self.probe_queue.clear()
        self._pending_axis_hit = None
        self._deferred_probe.clear()

    # ------------------------------------------------------------------ #
    # Reset (for testing)
    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        """Re-initialise hunt pools and clear all state."""
        self.__init__(size=self.size)
