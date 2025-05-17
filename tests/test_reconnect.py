import pytest
import socket

from beer.reconnect_controller import ReconnectController


def test_attach_once_succeeds_and_duplicate_rejected():
    registry = {}
    # Dummy notify function
    notify = lambda slot, msg: None
    rc = ReconnectController(0.1, notify, "tok1", "tok2", registry)
    sock1 = socket.socket()
    try:
        assert rc.attach_player("tok1", sock1) is True
        sock2 = socket.socket()
        assert rc.attach_player("tok1", sock2) is False
    finally:
        sock1.close()


def test_unknown_token_rejected():
    registry = {}
    notify = lambda slot, msg: None
    rc = ReconnectController(0.1, notify, "tokA", "tokB", registry)
    sock = socket.socket()
    try:
        assert rc.attach_player("badtoken", sock) is False
    finally:
        sock.close()
