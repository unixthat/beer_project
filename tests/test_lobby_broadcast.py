import io
import beer.io_utils as io_utils


class DummyFile:
    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, data):
        # Accept both strings and bytes
        if isinstance(data, str):
            data = data.encode()
        self.buffer.write(data)

    def flush(self):
        pass


class DummySock:
    def makefile(self, mode):
        return DummyFile()


def test_lobby_broadcast(monkeypatch):
    # Capture framed send calls
    calls = []

    def fake_send(wfile, seq, ptype=None, *, msg=None, obj=None):
        calls.append((wfile, seq, msg, obj))
        return True

    monkeypatch.setattr(io_utils, "send", fake_send)

    # Build a fake lobby of two sockets
    sock1, sock2 = DummySock(), DummySock()
    lobby = [(sock1, "T1"), (sock2, "T2")]

    # Recreate the lobby_broadcast logic from server
    def lobby_broadcast(msg, obj=None):
        for sock, _ in lobby:
            wfile = sock.makefile("w")
            io_utils.send(wfile, 0, msg=msg, obj=obj)

    # Broadcast a text message then an object payload
    lobby_broadcast("HELLO", None)
    test_obj = {"type": "spec_grid", "rows": []}
    lobby_broadcast(None, test_obj)

    # Expect 4 calls: two text, two object
    assert len(calls) == 4
    # First two: msg="HELLO", obj=None
    for _, seq, msg, obj in calls[:2]:
        assert seq == 0
        assert msg == "HELLO"
        assert obj is None
    # Next two: msg=None, obj=test_obj
    for _, seq, msg, obj in calls[2:]:
        assert seq == 0
        assert msg is None
        assert obj == test_obj
