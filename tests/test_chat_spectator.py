import socket
from beer.io_utils import send
from beer.common import PacketType
from conftest import TestClient

# prevent pytest from treating this helper as a test class
TestClient.__test__ = False

def test_chat_visible_to_spectator(game_factory):
    # Start a two-player session
    c1, c2, sess = game_factory()
    # Wait until Player 1 sees their "YOUR TURN" prompt (so recv_turn is active)
    c1.recv_until("YOUR TURN")

    # Create a spectator socketpair
    spec_srv, spec_cli = socket.socketpair()
    spec = TestClient(spec_cli)

    # Override the session's broadcast to send CHAT frames to spectator
    sess._broadcast = lambda payload, obj=None: send(
        spec_srv.makefile("w"), 0, PacketType.CHAT, obj=payload
    )

    # 1) Player 1 → delivered to Player 2 and Spectator
    msg1 = "FROM_P1"
    c1.send(f"CHAT {msg1}\n")
    assert msg1 in c2.recv_until(msg1)
    assert msg1 in spec.recv_until(msg1)

    # 2) Player 2 → delivered to Player 1 and Spectator
    msg2 = "FROM_P2"
    c2.send(f"CHAT {msg2}\n")
    assert msg2 in c1.recv_until(msg2)
    assert msg2 in spec.recv_until(msg2)

    # 3) Spectator → should NOT deliver to any player
    spec_msg = "FROM_SPEC"
    spec.send(f"CHAT {spec_msg}\n")
    assert spec_msg not in c1.recv_until(spec_msg)
    assert spec_msg not in c2.recv_until(spec_msg)
