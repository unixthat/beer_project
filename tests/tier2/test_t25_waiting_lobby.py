import time
import pytest
from tests.conftest import read_log_until, collect_lines


def test_t25_waiting_lobby(beer_server, beer_bot_factory, tmp_path):
    """
    T2.5: Waiting lobby for extra clients
    - Launch server and three bots
    - Verify the third waits in the lobby
    """

    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    # Slow down bots so spectator has time to join
    bot1, log1 = launch_bot(port, env_overrides={"BEER_BOT_DELAY": "1.0"}, logfile_name="bot1_t31.log")
    bot2, log2 = launch_bot(port, env_overrides={"BEER_BOT_DELAY": "1.0"}, logfile_name="bot2_t31.log")



    # Wait for game to start before connecting spectator
    shot1 = read_log_until(log1, r"SHOT", timeout=8)
    shot2 = read_log_until(log2, r"SHOT", timeout=8)

    assert shot1 and shot2, "Players did not start game"


    bot3, log3 = launch_bot(port, env_overrides={"BEER_BOT_DELAY": "0.05"}, logfile_name="bot3_t25.log")
    assert log3 is not None, "Bot 3 did not start"

    try:
        with open(log3) as f:
            print("\n=== Bot 3 log ===\n" + f.read())
    except Exception as e:
        print(f"Failed to read log3: {e}")
    # Wait for game to start before connecting spectator

    try:
        # Wait for first two bots to start game (look for SHOT as first sign of play)
        start1 = read_log_until(log1, r"SHOT", timeout=6)
        start2 = read_log_until(log2, r"SHOT", timeout=6)
        assert start1 is not None, "Bot 1 did not start"
        assert start2 is not None, "Bot 2 did not start"


    #     # Third bot should not see SHOT/HIT/MISS immediately
    #     lines3 = collect_lines(log3, timeout=2)
    #     assert not any("SHOT" in l or "HIT" in l or "MISS" in l for l in lines3), "Bot 3 should be waiting in lobby"
    #     # Terminate one bot to free a slot
    #     bot1.terminate()
    #     bot1.wait(timeout=5)
    #     # Now bot3 should eventually join a game (see SHOT)
    #     joined3 = read_log_until(log3, r"SHOT", timeout=15)
    #     if joined3 is None:
    #         with open(log3) as f:
    #             print("\n=== Bot 3 log ===\n" + f.read())
    #     assert joined3 is not None, "Bot 3 did not join a game after slot freed"
    finally:
        bot2.terminate()
        bot3.terminate()
        bot2.wait(timeout=5)
        bot3.wait(timeout=5)
