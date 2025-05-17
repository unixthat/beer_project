import pytest
import socket
import threading
from beer.session import GameSession
from beer.server import PID_REGISTRY


class TestClient:
    """Simple client wrapper for integration tests over framed protocol."""
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def send(self, msg: str) -> None:
        """Send a message terminated by newline."""
        self.sock.sendall(msg.encode())

    def recv_until(self, token: str, timeout: float = 2.0) -> str:
        """Read raw bytes until the uppercase token appears or timeout."""
        token_upper = token.upper()
        buf = b""
        self.sock.settimeout(timeout)
        try:
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                # Case-insensitive search
                if token_upper in buf.decode('utf-8', errors='ignore').upper():
                    break
        except socket.timeout:
            pass
        # Return decoded buffer, ignoring errors
        return buf.decode('utf-8', errors='ignore')

    def close(self) -> None:
        """Close the underlying socket."""
        self.sock.close()


@pytest.fixture
def game_factory() -> callable:
    """Factory that sets up a GameSession and returns two TestClients and the session."""
    def _factory():
        # Create server/client socket pairs for two players
        s1_srv, s1_cli = socket.socketpair()
        s2_srv, s2_cli = socket.socketpair()
        # Event to signal when placement/handshake done
        session_ready = threading.Event()
        # Arbitrary tokens
        t1 = "FACTORY1"
        t2 = "FACTORY2"
        # Instantiate and start session thread
        sess = GameSession(s1_srv, s2_srv, token_p1=t1, token_p2=t2, session_ready=session_ready)
        sess.start()
        # Wait for initial handshake and placement to complete
        session_ready.wait(timeout=2.0)
        # Wrap client ends
        c1 = TestClient(s1_cli)
        c2 = TestClient(s2_cli)
        return c1, c2, sess
    return _factory


@pytest.fixture
def reconnect_client() -> callable:
    """Helper to simulate a reconnecting client by token."""
    def _reconnect(token: str):
        # Attach a fresh server-side socket to the ReconnectController
        rc = PID_REGISTRY[token]
        srv_sock, cli_sock = socket.socketpair()
        rc.attach_player(token, srv_sock)
        return TestClient(cli_sock)
    return _reconnect
