import time
import pytest
from pathlib import Path
from tests.conftest import read_log_until, collect_lines


def test_t31_spectator_receives_updates(beer_server, beer_bot_factory, tmp_path):
    """
    T3.1: >2 clients – extra clients become spectators
    - Launch server and three bots
    - First two play; third becomes spectator
    - Spectator receives INFO but never prints SHOT/HIT/MISS on its own turn
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    bot1, log1 = launch_bot(port, logfile_name="bot1_t31.log")
    bot2, log2 = launch_bot(port, logfile_name="bot2_t31.log")

    # Wait for game to start before connecting spectator
    shot1 = read_log_until(log1, r"SHOT", timeout=8)
    shot2 = read_log_until(log2, r"SHOT", timeout=8)
    assert shot1 and shot2, "Players did not start game"

    bot3, log3 = launch_bot(port, logfile_name="bot3_t31.log")  # spectator

    try:
        # Server log should record spectator attachment
        server_log = tmp_path / "server.log"
        spect_entry = read_log_until(server_log, r"Spectator attached", timeout=5)
        assert spect_entry is not None, "Server did not log spectator attachment"
        collect_lines(log3, timeout=5)  # wait to accumulate
        with open(log3) as f:
            lines3 = f.readlines()
        # Spectator should receive game updates (HIT/MISS/SUNK) but never send its own "SHOT" command.
        assert any(any(word in l for word in ["HIT", "MISS", "SUNK"]) for l in lines3), "Spectator did not receive game updates"
        assert not any(l.startswith("SHOT ") for l in lines3), "Spectator should not send SHOT commands"
    finally:
        bot1.terminate(); bot2.terminate(); bot3.terminate()
        bot1.wait(timeout=5); bot2.wait(timeout=5); bot3.wait(timeout=5)
        assert server_proc.poll() is None, "Server exited unexpectedly"
