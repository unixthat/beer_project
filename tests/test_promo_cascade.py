import io
import pytest

from beer.spectator_hub import SpectatorHub


class FakeSocket:
    def __init__(self, name):
        self.name = name
    def makefile(self, mode):
        # Return a simple StringIO for read/write
        return io.StringIO()
    def close(self):
        pass


def test_spectator_hub_promote_and_empty():
    notify_calls = []
    def notify_fn(wfile, msg, obj):
        notify_calls.append((wfile, msg, obj))

    spec = SpectatorHub(notify_fn)
    # Add two fake spectators
    sock1 = FakeSocket('s1')
    sock2 = FakeSocket('s2')
    spec.add(sock1)
    spec.add(sock2)
    # Initially, not empty
    assert not spec.empty()

    # Stub session to capture promotion
    class SessionStub:
        def __init__(self):
            self.promoted = []
            self.p1_sock = None
            self.p1_file_r = None
            self.p1_file_w = None
            self.p2_sock = None
            self.p2_file_r = None
            self.p2_file_w = None
        def _begin_match(self):
            self.promoted.append('begin_match')

    session = SessionStub()
    # Promote into slot 1: should bind sock1
    assert spec.promote(1, session) is True
    assert session.p1_sock is sock1
    assert session.p1_file_r is not None and hasattr(session.p1_file_r, 'read')
    assert session.p1_file_w is not None and hasattr(session.p1_file_w, 'write')
    assert session.promoted == ['begin_match']
    # Still one spectator left
    assert not spec.empty()

    # Promote again: should bind sock2
    assert spec.promote(1, session) is True
    assert session.p1_sock is sock2
    assert spec.empty() is True

    # No more spectators: promote returns False
    assert spec.promote(1, session) is False
    # Empty remains True
    assert spec.empty() is True

    # Verify notify_fn was called on add and promote steps
    # At least the initial add notifications
    assert any(msg == 'INFO YOU ARE NOW SPECTATING' for _, msg, _ in notify_calls)
