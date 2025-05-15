import time
import pytest
from tests.conftest import read_log_until, collect_lines

pytest.skip("T2.5 superseded by Tier-3 lobby reconnect implementation", allow_module_level=True)

def test_t25_waiting_lobby(beer_server, beer_bot_factory):
    """
    T2.5: Waiting lobby for extra clients
    - Launch server and three bots
    - Verify the third waits in the lobby
    - When a slot frees up, third bot is paired and game starts
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    bot1, log1 = launch_bot(port, logfile_name="bot1_t25.log")
    bot2, log2 = launch_bot(port, logfile_name="bot2_t25.log")
    bot3, log3 = launch_bot(port, logfile_name="bot3_t25.log")

    try:
        # Wait for first two bots to start game (look for SHOT as first sign of play)
        start1 = read_log_until(log1, r"SHOT", timeout=6)
        start2 = read_log_until(log2, r"SHOT", timeout=6)
        assert start1 is not None, "Bot 1 did not start"
        assert start2 is not None, "Bot 2 did not start"
        # Third bot should not see SHOT/HIT/MISS immediately
        lines3 = collect_lines(log3, timeout=2)
        assert not any("SHOT" in l or "HIT" in l or "MISS" in l for l in lines3), "Bot 3 should be waiting in lobby"
        # Terminate one bot to free a slot
        bot1.terminate()
        bot1.wait(timeout=5)
        # Now bot3 should eventually join a game (see SHOT)
        joined3 = read_log_until(log3, r"SHOT", timeout=15)
        if joined3 is None:
            with open(log3) as f:
                print("\n=== Bot 3 log ===\n" + f.read())
        assert joined3 is not None, "Bot 3 did not join a game after slot freed"
    finally:
        bot2.terminate()
        bot3.terminate()
        bot2.wait(timeout=5)
        bot3.wait(timeout=5)
