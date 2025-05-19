# replay protection abstraction module


class ReplayWindow:
    """Track received sequence numbers to prevent replay and allow limited out-of-order"""

    def __init__(self, window_size: int = 64):
        self.window_size = window_size
        self.highest_seq = -1
        self.received = set()

    def check(self, seq: int) -> bool:
        """Return True if seq is fresh and within window, False if replayed or too old"""
        if seq <= self.highest_seq - self.window_size:
            return False
        if seq in self.received:
            return False
        return True

    def update(self, seq: int) -> None:
        """Record receipt of seq number"""
        self.received.add(seq)
        if seq > self.highest_seq:
            self.highest_seq = seq
        # purge old seq numbers below highest_seq - window_size
        cutoff = self.highest_seq - self.window_size
        self.received = {s for s in self.received if s > cutoff}
