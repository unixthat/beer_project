import pytest

from beer.server import requeue_players


class DummySocket:
    def __init__(self, name):
        self.name = name
    def __repr__(self):
        return f"<DummySocket {self.name}>"


def make_dummy(name):
    """Return a DummySocket for tests."""
    return DummySocket(name)


def test_requeue_normal():
    lobby = []
    winner = (make_dummy('w1'), 't1')
    loser = (make_dummy('l1'), 't2')
    requeue_players(lobby, winner, loser, 'hit')
    assert lobby[0] == winner
    assert lobby[-1] == loser


def test_requeue_no_loser_on_timeout():
    lobby = []
    winner = (make_dummy('w2'), 't3')
    loser = (make_dummy('l2'), 't4')
    requeue_players(lobby, winner, loser, 'timeout')
    assert lobby == [winner]


def test_requeue_multiple_matches():
    lobby = []
    # First match
    w1 = (make_dummy('w1'), 't1')
    l1 = (make_dummy('l1'), 't2')
    requeue_players(lobby, w1, l1, 'hit')
    assert lobby[0] == w1 and lobby[-1] == l1
    # Next match: previous loser wins
    requeue_players(lobby, l1, w1, 'hit')
    assert lobby[0] == l1 and lobby[-1] == w1
