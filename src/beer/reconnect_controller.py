"""ReconnectController: manage reconnect wait window and token-based reattachment for two-player slots."""
import threading
import socket
from typing import Callable, Dict
from .io_utils import send as io_send

class ReconnectController:
    """
    Handles per-slot reconnect windows and token-based reattachment.
    """

    def __init__(
        self,
        timeout: float,
        notify_fn: Callable[[int, str], None],
        token1: str,
        token2: str,
        registry: Dict[str, 'ReconnectController'],
    ):
        self.timeout = timeout
        # Protect new_sockets for non-blocking rebind
        self._lock = threading.Lock()
        self.notify_fn = notify_fn
        self.token1 = token1
        self.token2 = token2
        self.registry = registry
        self.events = {1: threading.Event(), 2: threading.Event()}
        self.new_sockets: Dict[int, socket.socket] = {}
        # Register for reconnect tokens
        registry[token1] = self
        registry[token2] = self

    def try_rebind(self, slot: int) -> tuple[bool, socket.socket | None]:
        """
        If a fresh socket arrived for *slot*, pop it and return (True, sock).
        Otherwise return (False, None) without blocking.
        """
        with self._lock:
            sock = self.new_sockets.pop(slot, None)
            if sock:
                return True, sock
            return False, None

    def wait(self, slot: int) -> bool:
        """
        Notify the survivor and wait up to timeout for reattachment.
        Returns True if the original player reattached in time.
        """
        other = 2 if slot == 1 else 1
        # Log server-side disconnect event
        print(f"[INFO] Player {slot} disconnected – waiting up to {self.timeout}s for reconnect")
        # Notify the surviving player that we're holding the slot
        self.notify_fn(other, f"INFO Opponent disconnected – holding slot for {self.timeout}s")
        evt = self.events[slot]
        reattached = evt.wait(timeout=self.timeout)
        if reattached:
            # Log server-side reconnection
            print(f"[INFO] Player {slot} reconnected successfully")
            # Acknowledge rejoin to both sides
            self.notify_fn(other, "INFO Opponent has reconnected – resuming match")
            self.notify_fn(slot, "INFO You have reconnected – resuming match")
            evt.clear()
        return reattached

    def attach_player(self, token: str, sock: socket.socket) -> bool:
        """
        Attach a reconnecting player by token; returns True on success.
        """
        if token == self.token1:
            slot = 1
        elif token == self.token2:
            slot = 2
        else:
            return False
        # Prevent duplicate reconnect attempts on the same slot
        if slot in self.new_sockets:
            # Token already in use: send error and close new socket
            wfile = sock.makefile("w")
            sent = io_send(wfile, 0, msg="ERR token-in-use")
            if not sent:
                # Fallback raw write if framing failed
                try:
                    wfile.write("ERR token-in-use\n")
                    wfile.flush()
                except Exception:
                    pass
            sock.close()
            return False
        # Store new socket and signal waiters
        self.new_sockets[slot] = sock
        self.events[slot].set()
        # No flush needed: previous accept loop consumed the handshake
        return True

    def take_new_socket(self, slot: int) -> socket.socket:
        """Retrieve and remove the new socket for the given slot."""
        return self.new_sockets.pop(slot)
