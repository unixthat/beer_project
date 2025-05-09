"""Integration test starting the server and connecting a socket client."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Optional, Type
from typing_extensions import Literal

import pytest
from beer.common import unpack, PacketType

PACKAGE_ROOT = Path(__file__).resolve().parents[1].joinpath("src")


class ServerProcess:
    """Context manager that runs `python -m beer.server`."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.proc: Optional[subprocess.Popen[bytes]] = None

    def __enter__(self) -> "ServerProcess":
        python = sys.executable
        env = {**dict(**{}), "PYTHONPATH": str(PACKAGE_ROOT), "BEER_PORT": str(self.port)}
        self.proc = subprocess.Popen(
            [python, "-m", "beer.server"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # Give it a moment to start
        time.sleep(1)
        if self.proc.poll() is not None:
            out = self.proc.stdout.read().decode() if self.proc.stdout else ""
            raise RuntimeError(f"Server failed to start. Output:\n{out}")
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
def test_server_accepts_connection() -> None:
    """Ensure the packaged server accepts a TCP connection and responds."""
    # Pick an ephemeral free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tmp:
        tmp.bind(("127.0.0.1", 0))
        port = tmp.getsockname()[1]
    with ServerProcess(port):
        # Connect two clients so that the game session actually starts.
        sock1 = socket.create_connection(("127.0.0.1", port))
        sock2 = socket.create_connection(("127.0.0.1", port))

        sock1.settimeout(5)
        sock2.settimeout(5)

        f1 = sock1.makefile("rb")
        f2 = sock2.makefile("rb")

        ptype1, seq1, obj1 = unpack(f1)  # type: ignore[arg-type]
        ptype2, seq2, obj2 = unpack(f2)  # type: ignore[arg-type]

        assert ptype1 == PacketType.GAME
        assert ptype2 == PacketType.GAME
        assert obj1.get("msg", "").startswith("START")
        assert obj2.get("msg", "").startswith("START")

        sock1.close()
        sock2.close()
