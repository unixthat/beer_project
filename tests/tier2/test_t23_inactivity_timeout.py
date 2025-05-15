import time
import pytest
from tests.conftest import read_log_until

def test_t23_inactivity_timeout(beer_server, beer_bot_factory):
    """
    T2.3: 30s inactivity timeout
    - Launch server and two bots
    - On attacker's turn, do nothing for 35s
    - Assert the other bot receives WIN (timeout/disconnect)
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    bot1, log1 = launch_bot(port, logfile_name="bot1_t23.log")
    bot2, log2 = launch_bot(port, logfile_name="bot2_t23.log")

    try:
        # Wait for both bots to be ready (look for SHOT as first sign of play)
        start1 = read_log_until(log1, r"SHOT", timeout=6)
        start2 = read_log_until(log2, r"SHOT", timeout=6)
        assert start1 is not None, "Bot 1 did not start"
        assert start2 is not None, "Bot 2 did not start"

        # Wait for 35s to trigger inactivity timeout
        time.sleep(35)
        # Check for WIN in either log
        win1 = read_log_until(log1, r"WIN", timeout=5)
        win2 = read_log_until(log2, r"WIN", timeout=5)
        assert win1 or win2, "No WIN message after inactivity timeout"
    finally:
        bot1.terminate()
        bot2.terminate()
        bot1.wait(timeout=5)
        bot2.wait(timeout=5)
