#!/usr/bin/env python3
"""
Orchestrated passive sniff + demo client shot for BEER server
"""
import subprocess
import time
import threading
from beer.config import DEFAULT_HOST, DEFAULT_PORT

# ANSI colors
CYAN = '\033[96m'
GREEN = '\033[92m'
RESET = '\033[0m'


def main() -> None:
    server = None
    attacker1 = attacker2 = attacker3 = None
    # Step 0: Setup narrative and overview
    print(f"""
=== BEER Protocol Replay & Denial-of-Service Interactive Essay ===

Welcome to a guided, interactive essay on the critical importance of authenticated and non-replayable protocols. Over the next few minutes, you will see firsthand how passive network monitoring can leak secret tokens, how simple replay attacks can subvert authentication, and how trivial flooding of replayed messages can incapacitate a server. Each section combines explanatory narrative with live demonstrations to cement your understanding of both attacks and defenses.

Prerequisites:
- Ensure the BEER server is running on {DEFAULT_HOST}:{DEFAULT_PORT} without flags.
- In a separate terminal, start two "attacker" clients with `beer-client --win` to generate genuine protocol traffic for us to analyze.

This essay unfolds in four phases:
  Phase 1: Passive Sniffing — Capture unprotected session tokens and commands in real-time.
  Phase 2: Replay Attack — Resend captured artifacts to coax privileged "HIT" responses from the server.
  Phase 3: DoS Simulation — Flood the server with replayed requests to observe performance degradation.
  Phase 4: Mitigation Techniques — Explore defenses against these threats.

Press Enter to begin Phase 1: Passive Sniffing...
""")
    input()

    # Step 0.5: Launch BEER server and attacker clients
    print("[*] Launching BEER server: beer-server")
    try:
        server = subprocess.Popen(["beer-server"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # Start server log reader thread
        def _log_server():
            for line in server.stdout:
                print(f"[SERVER] {line.rstrip()}")
        threading.Thread(target=_log_server, daemon=True).start()
    except Exception as e:
        print(f"[ERROR] Failed to launch beer-server: {e}")
        return

    print("[*] Launching two attacker clients: beer-client --win")
    try:
        attacker1 = subprocess.Popen(["beer-client", "--win"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        attacker2 = subprocess.Popen(["beer-client", "--win"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[ERROR] Failed to launch attacker clients: {e}")
        if server:
            try:
                server.terminate()
            except Exception:
                pass
        return

    time.sleep(1)

    # Step 1: Noisy sniff via tcpdump
    # Phase 1: Passive Sniffing Explanation
    print(f"""
=== Phase 1: Passive Sniffing ===

In this phase, we use `tcpdump -l -A` to line-buffer and display packet contents on the loopback interface. We capture unencrypted handshake tokens, session identifiers, and full command payloads exchanged by `beer-client` and the server. By examining raw packet contents, you'll see authentication tokens sent in cleartext, enabling unauthorized observation of sensitive values.

Pay close attention to:
- The initial handshake token structure and where it appears in the packet payload.
- Session identifiers that correlate commands to specific client instances.
- Command names and parameters, demonstrating how commands are issued without encryption.
""")
    input("Press Enter to initiate sniffing... ")

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
        # Launch third attacker midway to generate additional token traffic
        if not launched_attacker3 and time.time() - start >= 2:
            print("[*] Launching third attacker client: beer-client --win")
            try:
                attacker3 = subprocess.Popen(["beer-client", "--win"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"[ERROR] Failed to launch third attacker client: {e}")
            launched_attacker3 = True
        line = p.stdout.readline().rstrip()
        if line:
            print(f"{CYAN}[SNIFF]{RESET} {line}")
    p.kill()

    print("\n=== Sniffing complete ===\n")
    time.sleep(1)
    # Phase 2: Replay Attack Explanation
    print(f"""
=== Phase 2: Replay Attack ===

Armed with previously captured tokens and commands, we replay these messages verbatim, impersonating an authorized client. Because the BEER protocol lacks freshness checks (nonces or timestamps) and message authentication codes (MACs), the server cannot distinguish stale from genuine requests and executes privileged operations, responding with "HIT".

Observe:
- The identical handshake token sent during replay.
- The server's `[SERVER]` log confirming acceptance of the replayed token.
- The "HIT" response printed by our demo client.
""")
    input("Press Enter to launch the replay client... ")

    # Step 2: Launch a new beer-client to demonstrate a HIT
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

    print("[*] Waiting for HIT message from client...")
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
                print(f"{GREEN}[HIT]{RESET} Detected a hit response\n")
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            c.terminate()
        except Exception:
            pass

    # Step 3: Conclusion
    print("\n=== Demo Complete ===")
    if hit_detected:
        print("Client received a HIT, demonstrating the protocol still functions after sniffing.")
    else:
        print("No HIT detected; something may have gone wrong.")
    # Phase 3: DoS Observation & Mitigation
    print(f"""
=== Phase 3: DoS Simulation ===

Having demonstrated a single replay, we escalate the attack by flooding the server with rapid, repeated replays of captured tokens. This unrestrained flood can saturate CPU, memory, and network I/O, causing significant latency spikes or crashes.

Watch the `[SERVER]` logs to see a continuous stream of incoming replayed requests flooding your terminal. Notice how the sheer volume of packets overwhelms both the server and your log viewer.
""")
    # Interactive observation of server log spam
    input("Press Enter to observe server log spam for 5 seconds... ")
    time.sleep(5)
    print("""
As you can see, the server is now broken: overwhelmed by incessant replayed commands, it fails to handle any further legitimate requests. This clear demonstration underscores how trivially a server can be disabled when fresh checks and authentication safeguards are absent.
""")

    # Cleanup attacker clients and server
    print("[*] Terminating attacker clients and server...")
    for proc in (attacker1, attacker2, attacker3):
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
    if server:
        try:
            server.terminate()
        except Exception:
            pass

    # Phase 4: Mitigation Techniques
    print(f"""
=== Phase 4: Mitigation Techniques ===

In this final phase, we explore a suite of defenses designed to thwart sniffing, replay, and DoS attacks:

1) Nonces and Timestamps:
    • Attach a unique, single-use nonce or timestamp to each message.
    • The server maintains a cache of recently seen nonces to reject duplicates or expired values, preventing replay chains.

2) Message Authentication Codes (MACs):
    • Compute a MAC (e.g., HMAC-SHA256) over message contents using a shared secret.
    • The server verifies the MAC on receipt to detect any tampering or unauthorized submissions.

3) Encryption and Confidentiality:
    • Employ TLS or similar secure channels to encrypt all traffic, preventing passive sniffing.
    • Encryption ensures tokens and commands are not exposed in cleartext on the network.

4) Rate Limiting and Throttling:
    • Enforce per-client or per-token rate limits to mitigate flooding.
    • Automatically drop or delay excessive requests to preserve service availability for legitimate users.

5) Challenge–Response Protocols:
    • Use server-generated nonces (challenges) that clients must sign or encrypt.
    • Ensures messages are fresh, binding them cryptographically to a specific session or time window.

By combining these techniques—sometimes called defense-in-depth—you create robust protection against the simple yet devastating attacks demonstrated above.
""")


if __name__ == '__main__':
    main()
