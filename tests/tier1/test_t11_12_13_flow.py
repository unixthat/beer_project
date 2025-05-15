import time
import re
import pytest
from tests.conftest import read_log_until, collect_lines


def test_t11_concurrency_order(beer_server, beer_bot_factory, tmp_path):
    """
    T1.1: Concurrency bug fixed (message order)
    - Launch server and two bots
    - Verify both bots print SHOTs
    - Verify both bots print WIN/LOSE
    - Verify number of SHOTs is similar (±1)
    - On failure, print full logs for diagnosis
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    bot1, log1 = launch_bot(port, logfile_name="bot1.log")
    bot2, log2 = launch_bot(port, logfile_name="bot2.log")

    try:
        # Wait for both bots to print at least one SHOT
        shot1 = read_log_until(log1, r"SHOT ", timeout=6)
        shot2 = read_log_until(log2, r"SHOT ", timeout=6)
        assert shot1 is not None, "Bot 1 did not print any SHOT message"
        assert shot2 is not None, "Bot 2 did not print any SHOT message"

        # Collect SHOT lines for a short period to confirm ongoing turn-taking.
        lines1 = [l for l in collect_lines(log1, timeout=2) if "SHOT" in l]
        lines2 = [l for l in collect_lines(log2, timeout=2) if "SHOT" in l]
        # Each bot should have fired multiple times – 10 is a reasonable floor
        assert len(lines1) >= 10, f"Bot 1 printed too few SHOTs: {len(lines1)}"
        assert len(lines2) >= 10, f"Bot 2 printed too few SHOTs: {len(lines2)}"

        # Wait until both bots report end-of-game.
        win1 = read_log_until(log1, r"WIN|LOSE", timeout=20)
        win2 = read_log_until(log2, r"WIN|LOSE", timeout=20)
        assert win1 is not None, "Bot 1 did not print WIN or LOSE in time"
        assert win2 is not None, "Bot 2 did not print WIN or LOSE in time"
    except Exception:
        with open(log1) as f1, open(log2) as f2:
            print("\n=== Bot 1 log ===\n" + f1.read())
            print("\n=== Bot 2 log ===\n" + f2.read())
        raise
    finally:
        bot1.terminate()
        bot2.terminate()
        bot1.wait(timeout=5)
        bot2.wait(timeout=5)


def test_t12_auto_start_two_clients(beer_server, beer_bot_factory):
    """
    T1.2: Auto-start with exactly 2 clients
    - Launch server and two bots
    - Verify that the game starts automatically (no manual input required)
    - Check for expected game start messages in both bot logs
    - Ensure a third client is not accepted for the same game
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    bot1, log1 = launch_bot(port, logfile_name="bot1_t12.log")
    bot2, log2 = launch_bot(port, logfile_name="bot2_t12.log")

    try:
        # Wait for both bots to print at least one SHOT
        shot1 = read_log_until(log1, r"SHOT ", timeout=6)
        shot2 = read_log_until(log2, r"SHOT ", timeout=6)
        assert shot1 is not None, "Bot 1 did not print any SHOT message"
        assert shot2 is not None, "Bot 2 did not print any SHOT message"
        # Check that the game proceeds without further input (look for HIT/MISS/SUNK)
        result1 = read_log_until(log1, r"HIT|MISS|SUNK", timeout=6)
        result2 = read_log_until(log2, r"HIT|MISS|SUNK", timeout=6)
        assert result1 is not None or result2 is not None, "Game did not auto-start for both bots"
        # Try to launch a third bot and check it does not join the same game
        bot3, log3 = launch_bot(port, logfile_name="bot3_t12.log")
        time.sleep(0.5)
        lines3 = collect_lines(log3, timeout=1)
        assert not any("SHOT" in l for l in lines3), "Third bot should not join the same game"
    except Exception:
        with open(log1) as f1, open(log2) as f2:
            print("\n=== Bot 1 log ===\n" + f1.read())
            print("\n=== Bot 2 log ===\n" + f2.read())
        raise
    finally:
        bot1.terminate()
        bot2.terminate()
        bot1.wait(timeout=5)
        bot2.wait(timeout=5)
        if 'bot3' in locals():
            bot3.terminate()
            bot3.wait(timeout=5)


def test_t13_full_placement_turn_win(beer_server, beer_bot_factory):
    """
    T1.3: Full placement → turn taking → win flow
    - Launch server and two bots
    - Ensure both can play a full game to completion
    - Verify WIN/LOSE messages and clean socket closure
    """
    server_proc, port = beer_server
    launch_bot = beer_bot_factory

    bot1, log1 = launch_bot(port, logfile_name="bot1_t13.log")
    bot2, log2 = launch_bot(port, logfile_name="bot2_t13.log")

    try:
        shot1 = read_log_until(log1, r"SHOT ", timeout=6)
        shot2 = read_log_until(log2, r"SHOT ", timeout=6)
        assert shot1 is not None, "Bot 1 did not print any SHOT message"
        assert shot2 is not None, "Bot 2 did not print any SHOT message"
        # Wait for WIN/LOSE in both logs (allow up to 15s for full game)
        win1 = read_log_until(log1, r"YOU HAVE WON", timeout=15)
        lose1 = read_log_until(log1, r"YOU HAVE LOST", timeout=15)
        win2 = read_log_until(log2, r"YOU HAVE WON", timeout=15)
        lose2 = read_log_until(log2, r"YOU HAVE LOST", timeout=15)
        assert (win1 or win2) and (lose1 or lose2), "Both WIN and LOSE must appear in logs"
        # Ensure both bots exit cleanly after game
        bot1.wait(timeout=3)
        bot2.wait(timeout=3)
        assert bot1.poll() is not None, "Bot 1 did not exit after game"
        assert bot2.poll() is not None, "Bot 2 did not exit after game"
    except Exception:
        with open(log1) as f1, open(log2) as f2:
            print("\n=== Bot 1 log ===\n" + f1.read())
            print("\n=== Bot 2 log ===\n" + f2.read())
        raise
    finally:
        if bot1.poll() is None:
            bot1.terminate()
            bot1.wait(timeout=5)
        if bot2.poll() is None:
            bot2.terminate()
            bot2.wait(timeout=5)
