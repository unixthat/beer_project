import pytest
import socket
import threading
from beer.session import GameSession
from beer.server import PID_REGISTRY
from beer.common import recv_pkt, pack, PacketType
import logging

# Suppress INFO & DEBUG logs from server threads during tests
logging.basicConfig(level=logging.WARNING)


class TestClient:
    """Simple client wrapper for integration tests over framed protocol."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def send(self, msg: str) -> None:
        """Send a framed GAME packet with the given message."""
        # Frame the message as a GAME packet
        data = pack(PacketType.GAME, 0, {"msg": msg.strip()})
        self.sock.sendall(data)

    def recv_until(self, token: str, timeout: float = 2.0) -> str:
        """Read BEER protocol frames until the token appears in a decoded message."""
        self.sock.settimeout(timeout)
        buf = ""
        try:
            while True:
                ptype, seq, obj = recv_pkt(self.sock.makefile("rb"))
                msg = obj.get("msg", "") if isinstance(obj, dict) else ""
                buf += msg
                if token.upper() in msg.upper():
                    break
        except socket.timeout:
            pass
        return buf

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
        sess = GameSession(
            s1_srv,
            s2_srv,
            token_p1=t1,
            token_p2=t2,
            session_ready=session_ready,
            broadcast=lambda *_: None,
        )
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
