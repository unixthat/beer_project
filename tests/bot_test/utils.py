import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Tuple, List


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_match(*, timeout: int = 60) -> Tuple[str, str]:
    """Start server and two bots; return their stdout texts (bot1, bot2)."""
    port = _free_port()
    python = sys.executable
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(project_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["BEER_PORT"] = str(port)

    srv = subprocess.Popen([python, "-m", "beer.server"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    time.sleep(0.6)  # give server time to start

    bots: List[subprocess.Popen[str]] = []
    for _ in range(2):
        p = subprocess.Popen([python, "-m", "beer.bot", "--host", "127.0.0.1", "--port", str(port), "-v"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        bots.append(p)

    outs: List[str] = []
    for p in bots:
        try:
            out, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
        outs.append(out)

    with contextlib.suppress(Exception):
        srv.terminate()
        srv.communicate(timeout=5)

    return outs[0], outs[1]
