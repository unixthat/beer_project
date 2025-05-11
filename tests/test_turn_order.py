from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Optional, Type
from typing_extensions import Literal

# Ensure local src importable before we import beer
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from beer.common import unpack, PacketType

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src"

# Reset global encryption state in case previous tests enabled it
import beer.common as _bc
_bc._SECRET_KEY = None


class ServerProcess:
    """Spin up a temporary BEER server on an ephemeral port."""

    def __init__(self, port: int):
        self.port = port
        self.proc: Optional[subprocess.Popen[bytes]] = None

    def __enter__(self) -> "ServerProcess":
        python = sys.executable
        env = {**{}, "PYTHONPATH": str(PACKAGE_ROOT), "BEER_PORT": str(self.port)}
        self.proc = subprocess.Popen([python, "-m", "beer.server"], env=env, stdout=subprocess.DEVNULL)
        time.sleep(0.7)
        if self.proc.poll() is not None:
            raise RuntimeError("Server failed to start")
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        return False


@pytest.mark.timeout(10)  # type: ignore[arg-type]
def test_out_of_turn_shot_results_in_error() -> None:
    """Defender firing out-of-turn should receive an ERR and game must continue."""
    import beer.common as _bc; _bc._SECRET_KEY = None

    # Reserve free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tmp:
        tmp.bind(("127.0.0.1", 0))
        port = tmp.getsockname()[1]

    with ServerProcess(port):
        # Connect two clients
        s1 = socket.create_connection(("127.0.0.1", port))
        s2 = socket.create_connection(("127.0.0.1", port))
        s1.settimeout(5)
        s2.settimeout(5)
        f1 = s1.makefile("rb")
        f2 = s2.makefile("rb")

        # START frames
        p1, _, obj1 = unpack(f1)
        p2, _, obj2 = unpack(f2)
        assert p1 == p2 == PacketType.GAME
        assert obj1["msg"].startswith("START")
        assert obj2["msg"].startswith("START")

        # Send 'n' to skip manual placement prompts
        s1.sendall(b"n\n")
        s2.sendall(b"n\n")

        # Consume any placement grids/info before first turn starts
        for _ in range(20):
            p, _, o = unpack(f1)
            if isinstance(o, dict) and o.get('msg', '').startswith('INFO Your turn'):
                break
        # P2 is defender, send out-of-turn shot
        w2 = s2.makefile("w")
        w2.write("FIRE A1\n")
        w2.flush()

        # Expect ERR or placement wait message – loop until we hit ERR Not your turn
        for _ in range(10):
            p_err, _, o_err = unpack(f2)
            assert p_err == PacketType.GAME
            if "ERR" in o_err.get("msg", ""):
                assert "Not your turn" in o_err["msg"]
                break
        else:
            pytest.fail("Out-of-turn shot did not yield ERR")

        # Now Player 1 performs a valid shot to prove game still lives
        w1 = s1.makefile("w")
        w1.write("FIRE A1\n")
        w1.flush()
        # The server may first send back a GRID refresh; loop until we see shot outcome.
        for _ in range(5):
            p_resp, _, o_resp = unpack(f1)
            assert p_resp == PacketType.GAME
            if any(word in o_resp.get("msg", "") for word in ["HIT", "MISS", "ERR"]):
                break
        else:
            pytest.fail("Did not receive HIT/MISS after attacker fired")

        s1.close()
        s2.close()
