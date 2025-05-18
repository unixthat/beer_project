# Reliability abstraction module

class RetransmissionBuffer:
    """Buffer sent frames for possible retransmission on NAK"""
    def __init__(self, buffer_size: int = 64):
        self.buffer_size = buffer_size
        self.buffer = {}

    def add(self, seq: int, frame: bytes) -> None:
        """Add a sent frame to buffer"""
        self.buffer[seq] = frame
        # ensure buffer size limit
        if len(self.buffer) > self.buffer_size:
            oldest = min(self.buffer)
            self.buffer.pop(oldest, None)

    def get(self, seq: int) -> bytes | None:
        """Retrieve a buffered frame by seq"""
        return self.buffer.get(seq)
