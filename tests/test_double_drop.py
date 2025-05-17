import pytest
from beer.session import GameSession


class DummySpec:
    def promote(self, idx, session):
        # No spectators to promote
        return False


class DummyReconFail:
    def __init__(self):
        self.wait_calls = []
    def wait(self, idx):
        # Always fail to reconnect
        self.wait_calls.append(idx)
        return False
    def take_new_socket(self, idx): 
        # Should not be called on failure
        raise AssertionError("take_new_socket should not be called on failed reconnection")


class DummyReconSuccess:
    def __init__(self):
        self.wait_calls = []
    def wait(self, idx):
        # Always succeed to reconnect
        self.wait_calls.append(idx)
        return True
    def take_new_socket(self, idx):
        return f"sock{idx}"


class DummySession:
    """
    Minimal session stub to test _handle_disconnects without full GameSession initialization.
    """
    def __init__(self, recon, spec):
        self.recon = recon
        self.spec = spec
        self.rebind_calls = []
        self.conclude_calls = []
    def _rebind_slot(self, idx, sock):
        self.rebind_calls.append((idx, sock))
    def _conclude(self, winner, *, reason):
        self.conclude_calls.append((winner, reason))


def test_double_drop_abandoned():
    # Both players fail to reconnect or promote => abandoned, Player 1 wins by default
    recon = DummyReconFail()
    spec = DummySpec()
    sess = DummySession(recon, spec)
    result = GameSession._handle_disconnects(sess, [1, 2])
    assert result is True
    # No rebind attempts
    assert sess.rebind_calls == []
    # Conclude called once with (1, 'abandoned')
    assert sess.conclude_calls == [(1, 'abandoned')]
    # Recon attempted for both slots
    assert recon.wait_calls == [1, 2]


def test_single_drop_timeout_disconnect():
    # Single player drop fails => opponent wins with timeout/disconnect
    recon = DummyReconFail()
    spec = DummySpec()
    sess = DummySession(recon, spec)
    result = GameSession._handle_disconnects(sess, [2])
    assert result is True
    assert sess.rebind_calls == []
    # Player 1 should win (opponent 2 failed)
    assert sess.conclude_calls == [(1, 'timeout/disconnect')]
    assert recon.wait_calls == [2]


def test_reconnect_and_rebind():
    # Player 1 reconnects successfully => rebind, no conclude
    recon = DummyReconSuccess()
    spec = DummySpec()
    sess = DummySession(recon, spec)
    result = GameSession._handle_disconnects(sess, [1])
    assert result is False
    assert sess.rebind_calls == [(1, 'sock1')]
    assert sess.conclude_calls == []
    assert recon.wait_calls == [1]


def test_mid_turn_resume(game_factory, reconnect_client):
    # Test that a mid-turn reconnect resumes game for attacker
    p1, p2, sess = game_factory()
    # Prime the game by firing first shot
    p1.send("FIRE A1\n")
    _ = p1.recv_until("GRID")
    # Drop attacker mid-turn
    p2.close()
    # Reconnect attacker
    p2 = reconnect_client(sess.token_p2)
    p2.send("FIRE B1\n")
    out = p1.recv_until("HIT")
    assert "HIT" in out  # game continued


