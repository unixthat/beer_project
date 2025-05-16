import pytest

import time
from tests.conftest import read_log_until

def test_t24_graceful_disconnect(beer_server, beer_bot_factory):
    """
    T2.4: Graceful disconnect detection
    - Launch server and two bots
    - Forcibly disconnect one bot
    - Assert the other receives WIN (timeout/disconnect)
    - Assert server remains running
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    bot1, log1 = launch_bot(port, logfile_name="bot1_t24.log")
    bot2, log2 = launch_bot(port, logfile_name="bot2_t24.log")

    try:
        # Wait for both bots to be ready (look for SHOT as first sign of play)
        start1 = read_log_until(log1, r"SHOT", timeout=8)
        start2 = read_log_until(log2, r"SHOT", timeout=8)
        assert start1 is not None, "Bot 1 did not start"
        assert start2 is not None, "Bot 2 did not start"

        # Forcibly terminate bot2
        bot2.terminate()
        bot2.wait(timeout=5)
        # Wait for up to 35s for disconnect timeout
        win1 = read_log_until(log1, r"WIN", timeout=35)
        if win1 is None:
            with open(log1) as f:
                print("\n=== Survivor Bot 1 log ===\n" + f.read())
        assert win1 is not None, "Survivor bot did not receive WIN after peer disconnect"
        # Check server is still running
        assert server_proc.poll() is None, "Server process exited after bot disconnect"
    finally:
        bot1.terminate()
        bot1.wait(timeout=5)
