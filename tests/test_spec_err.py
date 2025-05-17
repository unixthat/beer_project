import io
import select as real_select
import pytest

import beer.io_utils as io_utils
from beer.spectator_hub import SpectatorHub


class DummyRaw:
    def __init__(self, sock):
        self._sock = sock

class DummyBuffer:
    def __init__(self, raw):
        self.raw = raw

class DummyReader:
    def __init__(self, sock):
        self.buffer = DummyBuffer(DummyRaw(sock))

class DummyWriter:
    def __init__(self):
        self.buffer = io.BytesIO()


def test_spectator_command_guard(monkeypatch):
    # Set up a dummy session with one spectator socket
    dummy_sock = object()
    session = type('S', (), {})()
    session.spec = SpectatorHub(lambda *args: None)
    # Ensure run determines slot by defining file attributes
    session.p1_file_r = None  # stub, will be overridden
    session.p2_file_r = None
    # Inject dummy_sock as a spectator
    session.spec._sockets = [dummy_sock]
    # Initialize sequence and reconnect (not used here)
    session.io_seq = 7
    # Prepare dummy reader/writer and defender placeholders
    r = DummyReader(dummy_sock)
    # Bind readers for slot detection
    session.p1_file_r = r
    # defender reader/writer won't be used; provide arbitrary valid sock
    w = DummyWriter()
    def_sock = object()
    defender_r = DummyReader(def_sock)
    session.p2_file_r = defender_r
    defender_w = DummyWriter()

    # Monkey-patch select.select to first return our dummy_sock, then empty so loop exits
    responses = [([dummy_sock], [], []), ([], [], [])]
    def fake_select(read, write, exc, timeout):
        return responses.pop(0)
    monkeypatch.setattr(real_select, 'select', fake_select)

    # Monkey-patch safe_readline to return a command
    monkeypatch.setattr(io_utils, 'safe_readline', lambda file, on_disconnect, retry=True: 'FIRE A1\n')

    # Capture send calls
    calls = []
    def fake_send(writer, seq, ptype=None, *, msg=None, obj=None):
        calls.append((seq, msg))
        return True
    monkeypatch.setattr(io_utils, 'send', fake_send)

    # Call recv_turn, which should handle spectator guard and then exit
    result = io_utils.recv_turn(session, r, w, defender_r, defender_w)
    assert result is None
    # Expect exactly one send call with our error message and seq=7
    assert calls == [(7, 'ERR Spectators cannot issue commands')]
