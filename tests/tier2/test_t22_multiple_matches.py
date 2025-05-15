import time
import pytest
from tests.conftest import read_log_until, collect_lines

def test_t22_multiple_matches(beer_server, beer_bot_factory):
    """
    T2.2: Multiple matches, one server instance
    - Launch server and two bots, play a full game
    - Launch two new bots, verify a new game starts without restarting the server
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    # First game
    bot1a, log1a = launch_bot(port, logfile_name="bot1a_t22.log")
    bot2a, log2a = launch_bot(port, logfile_name="bot2a_t22.log")
    try:
        # Wait for both bots to play at least one SHOT
        shot1a = read_log_until(log1a, r"SHOT ", timeout=6)
        shot2a = read_log_until(log2a, r"SHOT ", timeout=6)
        assert shot1a is not None, "Bot 1a did not print any SHOT message"
        assert shot2a is not None, "Bot 2a did not print any SHOT message"
        # Wait for WIN/LOSE in both logs
        win1a = read_log_until(log1a, r"WIN|LOSE", timeout=8)
        win2a = read_log_until(log2a, r"WIN|LOSE", timeout=8)
        assert win1a or win2a, "First game did not complete"
    finally:
        bot1a.terminate()
        bot2a.terminate()
        bot1a.wait(timeout=5)
        bot2a.wait(timeout=5)

    # Second game
    bot1b, log1b = launch_bot(port, logfile_name="bot1b_t22.log")
    bot2b, log2b = launch_bot(port, logfile_name="bot2b_t22.log")
    try:
        shot1b = read_log_until(log1b, r"SHOT ", timeout=6)
        shot2b = read_log_until(log2b, r"SHOT ", timeout=6)
        assert shot1b is not None, "Bot 1b did not print any SHOT message"
        assert shot2b is not None, "Bot 2b did not print any SHOT message"
        # Wait for WIN/LOSE in both logs
        win1b = read_log_until(log1b, r"WIN|LOSE", timeout=8)
        win2b = read_log_until(log2b, r"WIN|LOSE", timeout=8)
        assert win1b or win2b, "Second game did not complete"
    finally:
        bot1b.terminate()
        bot2b.terminate()
        bot1b.wait(timeout=5)
        bot2b.wait(timeout=5)
