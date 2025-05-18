import io
import pytest

from beer.reconnect_controller import ReconnectController


class FakeSocket:
    def __init__(self):
        self.closed = False
        self.wfile = io.StringIO()

    def makefile(self, mode):
        if "w" in mode:
            return self.wfile
        raise ValueError("FakeSocket only supports writing")

    def close(self):
        self.closed = True


def test_token_collision_safeguard():
    registry = {}
    # Create controller with two tokens
    controller = ReconnectController(
        timeout=1.0,
        notify_fn=lambda *args: None,
        token1="tok1",
        token2="tok2",
        registry=registry,
    )
    # First attach should succeed
    sock1 = FakeSocket()
    assert controller.attach_player("tok1", sock1) is True

    # Second attach attempt with same token should fail
    sock2 = FakeSocket()
    result = controller.attach_player("tok1", sock2)
    assert result is False
    # Socket should be closed
    assert sock2.closed is True
    # Error message should be sent to the write buffer
    out = sock2.wfile.getvalue()
    assert "ERR token-in-use" in out


def test_attach_different_tokens():
    registry = {}
    controller = ReconnectController(
        timeout=1.0,
        notify_fn=lambda *args: None,
        token1="A",
        token2="B",
        registry=registry,
    )
    sockA = FakeSocket()
    sockB = FakeSocket()
    # Attaching both tokens in turn should succeed
    assert controller.attach_player("A", sockA) is True
    assert controller.attach_player("B", sockB) is True
