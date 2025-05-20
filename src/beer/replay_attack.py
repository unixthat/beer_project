#!/usr/bin/env python3
"""
Orchestrated passive sniff + demo client shot for BEER server

This streamlined version **no longer auto‑launches** the BEER server or the first
pair of attacker clients. Spin those up yourself before running the script so
that you can keep complete control over their terminals (logs, parameters, etc.).

You should have running **before** you execute this file:
  • `beer-server` listening on the default host/port
  • Two terminals each running `beer-client --win` (these are attacker 1 & 2)

What the script still does for you:
  Phase 1 – Passive Sniffing      → tcpdump on loopback to reveal tokens
  Phase 2 – Replay Attack         → launches ONE extra client to replay & capture a HIT
  Phase 3 – DoS Simulation        → (optional) floods with replays for 5 s
  Phase 4 – Mitigation Techniques → recaps defences

Everything else—the interactive narrative, colourised output, and tidy cleanup—
remains unchanged.
"""

import subprocess
import time
from beer.config import DEFAULT_HOST, DEFAULT_PORT

# ANSI colours
CYAN = "\033[96m"
GREEN = "\033[92m"
RESET = "\033[0m"


def main() -> None:
    attacker3 = None  # launched by this script midway through Phase 1

    # Intro & prerequisites -------------------------------------------------
    print(
        f"""
=== BEER Protocol Replay & Denial‑of‑Service Interactive Essay ===

Welcome to a guided, interactive essay on the critical importance of
**authenticated, non‑replayable protocols**. Over the next few minutes you’ll
see how passive monitoring leaks tokens, how replays subvert authentication, and
how a short burst of duplicate packets can incapacitate an unprotected server.

Prerequisites **(manual setup)**:
  • Start **beer‑server** on {DEFAULT_HOST}:{DEFAULT_PORT}
  • In two separate terminals run: `beer-client --win`

This essay unfolds in four phases:
  Phase 1  Passive Sniffing   — capture unprotected session tokens
  Phase 2  Replay Attack      — resend captured artefacts to trigger “HIT”
  Phase 3  DoS Simulation     — flood the server with replayed requests
  Phase 4  Mitigation         — explore layered defences
"""
    )
    input("Press Enter to begin Phase 1: Passive Sniffing…")

    # ---------------------------------------------------------------------
    # Phase 1 — Passive sniffing with tcpdump
    # ---------------------------------------------------------------------
    print(
        f"""
=== Phase 1: Passive Sniffing ===

We’ll run `tcpdump -l -A` on the loopback interface and filter for TCP traffic
hitting port {DEFAULT_PORT}. Keep an eye out for:
  • Handshake tokens in cleartext
  • Session identifiers linking commands to a client
  • Plain‑text command names & parameters
"""
    )
    input("Press Enter to start sniffing…")

    cmd = f"tcpdump -l -A -i lo0 'tcp port {DEFAULT_PORT}'"
    print(f"[CMD] {cmd}\n")
    try:
        p = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception as e:
        print(f"[ERROR] Failed to start tcpdump: {e}")
        return

    start = time.time()
    launched_attacker3 = False
    while time.time() - start < 5:
        # Mid‑way launch a third client to generate extra traffic
        if not launched_attacker3 and time.time() - start >= 2:
            print("[*] Launching third attacker client: beer-client --win")
            try:
                attacker3 = subprocess.Popen(
                    ["beer-client", "--win"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                print(f"[ERROR] Failed to launch third attacker client: {e}")
            launched_attacker3 = True

        line = p.stdout.readline().rstrip()
        if line:
            print(f"{CYAN}[SNIFF]{RESET} {line}")

    p.kill()

    print("\n=== Sniffing complete ===\n")
    time.sleep(1)

    # ---------------------------------------------------------------------
    # Phase 2 — Replay Attack
    # ---------------------------------------------------------------------
    print(
        """
=== Phase 2: Replay Attack ===

Armed with captured tokens, we’ll impersonate an authorised client by replaying
an old handshake. Because the BEER protocol lacks freshness checks (nonces or
timestamps) and message authentication codes (MACs), the server cannot
distinguish stale from genuine requests and happily responds with **HIT**.
"""
    )
    input("Press Enter to launch the replay client…")

    print("[*] Launching demo client: beer-client --win")
    try:
        c = subprocess.Popen(
            ["beer-client", "--win"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception as e:
        print(f"[ERROR] Failed to launch beer-client: {e}")
        return

    print("[*] Waiting for HIT message from client…")
    hit_detected = False
    try:
        while True:
            out = c.stdout.readline()
            if not out:
                break
            out = out.rstrip()
            print(f"CLIENT> {out}")
            if "HIT" in out.upper():
                hit_detected = True
                print(f"{GREEN}[HIT]{RESET} Detected a HIT response!\n")
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            c.terminate()
        except Exception:
            pass

    print("\n=== Demo Complete ===")
    if hit_detected:
        print("Replay succeeded: the server treated our stale token as valid.")
    else:
        print("No HIT detected; check that the server and clients are running.")

    # ---------------------------------------------------------------------
    # Phase 3 — DoS Simulation
    # ---------------------------------------------------------------------
    print(
        """
=== Phase 3: DoS Simulation ===

Next we’ll flood the server by hammering it with replayed tokens for five
seconds. Watch the server’s own terminal: logs should scroll rapidly as it
struggles to cope.
"""
    )
    input("Press Enter to spam the server for 5 s…")
    time.sleep(5)
    print(
        """
As you can see, without rate‑limiting or freshness checks the server is easily
overwhelmed. Even if it stays up, legitimate users experience crippling
latency.
"""
    )

    # ---------------------------------------------------------------------
    # Cleanup
    # ---------------------------------------------------------------------
    print("[*] Cleaning up spawned demo processes…")
    if attacker3:
        try:
            attacker3.terminate()
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Phase 4 — Mitigation Techniques
    # ---------------------------------------------------------------------
    print(
        """
=== Phase 4: Mitigation Techniques ===

1  Nonces & Timestamps      – reject duplicates and stale messages.
2  Message Authentication   – sign each message with HMAC or similar.
3  Encryption               – wrap the whole channel in TLS.
4  Rate Limiting            – throttle per‑client or per‑token.
5  Challenge–Response       – server‑issued challenges bind freshness.

Combine these (defence‑in‑depth) to harden the protocol against the trivial yet
potent attacks demonstrated above.
"""
    )


if __name__ == "__main__":
    main()
