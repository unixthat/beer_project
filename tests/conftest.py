import os
import socket
import subprocess
import time
import pytest
import sys
import pathlib
from beer import config as _cfg
import re

# Ensure project root is on sys.path so that `import tests.*` works even when
# PYTHONPATH is not set (e.g. direct `pytest tests/tier1`).  This makes the
# test suite robust across IDEs, CI and developer machines.
PROJECT_ROOT_PATH = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

# Ensure local src directory is on sys.path so that local code is imported before any installed package
SRC_PATH = PROJECT_ROOT_PATH / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(PROJECT_ROOT, '..'))

# Ensure persistent tests/logs directory exists for bot logs
os.makedirs(_cfg.TEST_LOG_DIR, exist_ok=True)

def introduce_bot_delay(delay: float = 0.0):
    """Ensure bots run with a small delay, typically used so a spectator can join before match concludes in testing."""
    # Only set if not already specified
    os.environ.setdefault("BEER_BOT_DELAY", delay)

def get_free_port() -> int:
    """Find a free port on localhost for test server/client."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="function")
def beer_server(tmp_path):
    """Launch the BEER server as a subprocess on a free port. Yields (proc, port)."""
    port = get_free_port()
    env = os.environ.copy()
    # Ensure server subprocess imports local code from src
    env["PYTHONPATH"] = str(PROJECT_ROOT_PATH / "src")
    env["BEER_PORT"] = str(port)
    logfile = tmp_path / "server.log"
    proc = subprocess.Popen([
        sys.executable, "-u", "-m", "beer.server", "--verbose"
    ], env=env, cwd=PROJECT_ROOT, stdout=logfile.open("w"), stderr=subprocess.STDOUT)
    # Wait for server to start
    time.sleep(1.0)
    yield proc, port
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="function")
def beer_client_factory(tmp_path):
    """Returns a function to launch a BEER client subprocess attached to a given port."""
    def _launch_client(port: int, extra_args=None, env_overrides=None, logfile_name=None):
        env = os.environ.copy()
        env["BEER_PORT"] = str(port)
        if env_overrides:
            env.update(env_overrides)
        args = ["python", "-m", "beer.client"]
        if extra_args:
            args.extend(extra_args)
        logfile = tmp_path / (logfile_name or f"client_{time.time_ns()}.log")
        proc = subprocess.Popen(args, env=env, stdout=logfile.open("w"), stderr=subprocess.STDOUT)
        return proc, logfile
    return _launch_client


@pytest.fixture(scope="function")
def beer_bot_factory(tmp_path):  # tmp_path retained for fixture signature compatibility (unused)
    """Launch BEER bot subprocesses writing logs to tests/logs directory."""

    def _launch_bot(port: int, extra_args=None, env_overrides=None, logfile_name=None):
        env = os.environ.copy()
        # Ensure bot subprocess imports local code
        env["PYTHONPATH"] = str(PROJECT_ROOT_PATH / "src")
        env["BEER_PORT"] = str(port)
        env["PYTHONUNBUFFERED"] = "1"
        if env_overrides:
            env.update(env_overrides)

        args = [sys.executable, "-u", "-m", "beer.bot", "--port", str(port)]
        if extra_args:
            args.extend(extra_args)

        logfile = _cfg.TEST_LOG_DIR / (logfile_name or f"bot_{time.time_ns()}.log")
        proc = subprocess.Popen(
            args,
            env=env,
            cwd=PROJECT_ROOT,
            stdout=logfile.open("w"),
            stderr=subprocess.STDOUT,
        )
        return proc, logfile

    return _launch_bot

# ------------------------------------------------------------
# Helper functions shared across tests (moved from helpers.py)
# ------------------------------------------------------------

def read_log_until(logfile, pattern, timeout=5):
    """Read lines from *logfile* until *regex pattern* matches or *timeout* seconds elapse.

    Returns the matching line or None if not found within the time limit.
    """
    deadline = time.time() + timeout
    pat = re.compile(pattern)
    with open(logfile, "r") as f:
        while time.time() < deadline:
            f.seek(0)
            lines = f.readlines()
            for line in lines:
                if pat.search(line):
                    return line
            time.sleep(0.1)
    return None


def collect_lines(logfile, timeout=10):
    """Continuously read *logfile* for *timeout* seconds and return the latest lines list."""
    lines: list[str] = []
    deadline = time.time() + timeout
    with open(logfile, "r") as f:
        while time.time() < deadline:
            f.seek(0)
            new_lines = f.readlines()
            if new_lines:
                lines = new_lines
            time.sleep(0.1)
    return lines
