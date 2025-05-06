# BEER – Battleships: Engage in Explosive Rivalry
CITS 3002 • High‑Distinction Implementation Plan (≤ 2 000 LOC)

---

## TL;DR (1 paragraph)

Implement BEER in **Python 3.11** with a `src/beer/` package (server, client, session, common).
A **thread-per-socket** lobby server continuously matches players, supports **spectators** and a **60 s reconnect window** (Tier 3), all driven by a single **Enum-based FSM**.
Network I/O uses a custom **16-byte frame + CRC-32** wire protocol (Tier 4.1) implemented in `common.py`; a `/chat <txt>` command is piggy-backed as `PacketType.CHAT` and broadcast to all clients (Tier 4.2).
Develop in a local **venv** for speed, but ship a multi-arch **Docker** image (`python:3.11-slim`) so the code runs identically on Apple Silicon and x86_64.
Quality gates: **Black + Flake8 + Mypy (strict) + pytest** via **pre‑commit** and a LOC CI check.
Everything spins up with one command (`python server.py` **or** `docker compose up`) and stays under ~1 450 production lines.

---

## 1 Why Python 3.11 ?

* Concise syntax → stays < 2 000 LOC while covering all tiers.
* Built‑in `socket`, `threading`, `enum`, `queue`, `zlib.crc32`.
* Readable for markers; cross‑platform out‑of‑the‑box.

---

## 2 Runtime Strategy (venv ↔ Docker)

| Task | venv | Docker |
|------|------|--------|
| Day‑to‑day coding | ✅ fastest, IDE friendly | ❌ slower build |
| Cross‑arch reproducibility | ❌ relies on host | ✅ identical Linux image |
| Marker convenience | ✅ if Python installed | ✅ one‑command run |

**Hybrid rule**
1. `python -m venv venv && pip install -r dev-requirements.txt` for dev.
2. `docker build -t beer .` for guaranteed parity (arm64/amd64).
Both documented; neither mandatory.

---

## 3 Directory Layout

```
.
├── README.md               ← this file
├── server.py               ← ≈300 LOC
├── client.py               ← ≈260 LOC
├── game.py                 ← ≈200 LOC
├── common.py               ← Packet, CRC‑32, helpers (≈120 LOC)
├── requirements.txt        ← (empty – std‑lib only)
├── dev-requirements.txt    ← black, flake8, mypy, pytest, pre-commit
├── Dockerfile              ← python:3.11‑slim multi‑arch
├── docker-compose.yml      ← demo: 1 server + 2 clients
├── .pre-commit-config.yaml ← auto format / lint / type / test
└── tests/
    ├── test_game.py        ← rules unit tests (≈120 LOC)
    └── test_integration.py ← spin server + 2 sockets (≈150 LOC)
```

---

## 4 Core Design

### 4.1 Enums (common.py)
```python
class Ship(Enum):
    CARRIER=5; BATTLESHIP=4; CRUISER=3; SUBMARINE=3; DESTROYER=2

class PacketType(Enum): GAME=0; CHAT=1; ACK=2; ERROR=3

class State(Enum):
    WAITING=0; PLACING=1; PLAYING=2; DISCONNECTED=3; GAME_OVER=4
```

### 4.2 State machine (server.py)
```python
TRANSITIONS = {
  (State.PLACING, "place_done"): State.PLAYING,
  (State.PLAYING, "hit"):        State.PLAYING,
  (State.PLAYING, "miss"):       State.PLAYING,
  (State.PLAYING, "win"):        State.GAME_OVER,
  (State.PLAYING, "disconnect"): State.DISCONNECTED,
  (State.DISCONNECTED, "rejoin"):State.PLAYING,
}
```

### 4.3 Frame format (Tier 4.1)
```
0‑1 : 0xBEER  • 2 : ver 1 • 3 : type • 4‑7 : seq u32
8‑11: len     • 12‑15 : CRC‑32(header[0:12]+payload) • 16‑… JSON
```

### 4.4 Tier coverage
| Tier | Files | Feature |
|------|-------|---------|
| 1 | server.py, client.py | 2-player, fixed sync |
| 2 | session.py | validation + 30 s inactivity |
| 3 | server.py, session.py | lobby queue, spectators, 60 s reconnect |
| 4.1 | common.py | custom frame + CRC-32 |
| 4.2 | common.py, session.py, client.py | `/chat` broadcast |

---

## 5 Tooling & Hooks

* **Black 24.4** – auto format
* **Flake8 7.0** – style & lint
* **Mypy 1.10 --strict** – static types
* **pytest 8.2** – tests
* **pre‑commit 3.7** – runs all of the above on every commit

`.pre-commit-config.yaml` already pins exact versions.

---

## 6 Run & Test

```bash
# dev (plaintext)
python -m venv venv && source venv/bin/activate
pip install -r dev-requirements.txt
python -m beer.server --port 5000         # terminal 1 (server, plaintext)
python -m beer.client --host 127.0.0.1 --port 5000  # terminal 2 (client A)
python -m beer.client --host 127.0.0.1 --port 5000  # terminal 3 (client B)

# dev (encrypted)
python -m beer.server --port 5001 --secure          # AES-CTR with default demo key
python -m beer.client --secure --port 5001          # each client opts-in too
#   custom key example (128-bit hex):
python -m beer.server --secure=DEAD...C0DE  # 32-char hex
python -m beer.client --secure=DEAD...C0DE

# container demo
docker compose up --build --scale client=2
```

*Tests*: `pytest -q` (unit + integration + crypto round-trip).
*LOC gate*: `cloc $(git ls-files '*.py' | grep -v tests) | awk '/^SUM/ {exit($5>2000)}'`.

---

## 7 Submission Checklist

- [x] All tiers fully implemented
- [x] Production LOC < 2 000
- [x] README (this file) updated with SIDs
- [x] Demo video ≤ 10 min
- [x] Zip named `<SID1>_<SID2>_BEER.zip`

Happy ship‑sinking — go bag that HD!

---

## 8 Roadmap to HD (Feature Milestones)

We'll progress through the following milestones in order—no fixed calendar, simply complete each step before moving on:

1. **Project boot-strap** – repository, virtual-env, CI pipeline; Black/Flake8/Mypy/pytest are green.
2. **Tier 1** – two-player network match, fixed turn sequencing, receiver thread in client.
3. **Tier 2** – input validation, 30 s inactivity timeout, multi-game loop.
4. **Tier 3 (part 1)** – lobby server, spectators receive live updates.
5. **Tier 3 (part 2)** – 60 s reconnect window with token; automatic next-match rotation.
6. **Tier 4.1** – custom 16-byte frame with CRC-32; refactor client/server I/O via `common.py`.
7. **Tier 4.2** – `/chat` broadcast piggy-backed on the same frame.
8. **Advanced-knowledge sprint** – add optional AES-CTR encryption & replay-attack mitigation (see §9) plus polish docs & tests.
9. **Release candidate** – full regression, demo video recording, LOC gate, packaging.

---

## 9 Advanced Networking Showcase (Tier 4 HD-level)

A fully working game plus packet framing already gets us to Distinction. To push into **HD** we will demonstrate deeper networking expertise with **two lightweight yet meaningful extensions**:

### 9.1 AES-CTR Encryption (optional runtime flag)
* **Why?** Shows understanding of confidentiality, IV reuse, and stream-cipher attacks.
* **How?**
  1. Add `--secure` CLI flag on both client & server.
  2. Derive a shared 128-bit key via pre-shared secret or simple DH key-exchange (pyca/cryptography).
  3. Encrypt **payload bytes only**; header (incl. CRC) remains in clear-text to retain integrity checks.
  4. Include a 64-bit nonce (packet seq) as CTR IV 108.
* **Assessment**: captures replay-attack surface & mitigation; minimal LOC (~80).

### 9.2 Security-flaw Analysis & Mitigation (T4.4)
* Craft replay exploit script (`exploit_replay.py`) that resends a valid *HIT* packet → server would previously duplicate state.
* After encryption + nonce enforcement the same script produces `ERROR Out-of-order`.

These two combined tick the rubric's "advanced knowledge" bullet without complicating gameplay logic.

---

## 10 Reporting & Demo Pointers

* **Report**
  * Clearly map each requirement ID (T1.1, T2.3 …) to commit hash & file.
  * Include packet diagrams, CRC pseudo-code, and encryption flowchart.
* **Demo video**
  1. Start server, join two players & one spectator.
  2. Showcase reconnection.
  3. Flip `--secure` flag → show hex dump of encrypted frame.
  4. Run replay exploit pre- & post-fix.

---

## 11 Tier 3 Deep-Dive — "Multiple Connections & Spectators"

Tier 3 elevates BEER from a simple two-player duel to a *live arena* capable of juggling dozens of sockets concurrently while still guaranteeing deterministic gameplay. The production code already implements the following mechanics, verified by `tests/test_integration.py`.

### 11.1 Lobby life-cycle
1. **Socket intake** – `beer.server` never blocks on `accept()`. Each fresh connection is classified immediately:
   * **Reconnect?** If the first line matches `TOKEN <hex>`, the socket is handed to an existing `GameSession` via `attach_player`, restoring the file objects and resuming play.
   * **Spectator?** If the current front-match is running, the socket is registered with `add_spectator()`. No extra threads: spectators reuse the session's broadcast writes.
   * **Waiting lobby** – otherwise the socket is queued until another unmatched player arrives; the pair is popped and a new `GameSession` thread starts.

2. **Thread model** – a lightweight *thread-per-socket* design keeps state isolation trivial: each player (or spectator) has a dedicated reader thread; writes are coordinated via the session object to avoid interleaving.

### 11.2 Spectator UX
Spectators receive the same framed packets (`PacketType.GAME` / `CHAT`) as players, but never the *turn prompt*. Any attempt to issue a command is answered with `ERROR spectator` and safely ignored by the FSM.

### 11.3 60 s Reconnect window
On `START`, each player receives an 8-byte random token. If the TCP link dies, the `GameSession` pauses, sets an `Event()`, and waits up to **60 s**. A reconnecting socket that transmits the token is re-attached transparently; otherwise the opponent wins by forfeit and spectators are informed.

### 11.4 Automatic next-match rotation
When a session ends its thread cleans up and the lobby loop immediately dequeues the next two waiting players (or connects fresh arrivals) and broadcasts `INFO Next match begins…` to any lingering spectators.

This architecture satisfies all Tier 3 rubric points while adding only ~150 LOC.

---

## 12 Outstanding / Next Steps

| Status | Task |
|--------|------|
| ✅ | **Wire `--secure` CLI flag** on both client & server. |
| ✅ | **Replay-attack proof-of-concept** (`exploit_replay.py`). |
| ☐ | **Insert actual SIDs** into filenames, README & report before submission. |

Everything else is complete and green; LOC headroom ≈ 450.

---

## 13 Architecture Overview (at a glance)

A concise picture of how the **server, client and wire-protocol** collaborate; distilled from the longer narrative in *deliverable.md*.

### 13.1 Server responsibilities
* **Connection intake** – accept TCP sockets, classify (player, spectator, reconnect) and dispatch.
* **Authoritative game state** – owns the boards, validates every move, prevents cheating.
* **GameSession FSM** – one thread per match governs turn order, time-outs (30 s inactivity) and win detection.
* **Concurrency** – simple *thread-per-socket*; Python GIL is no bottleneck because gameplay is I/O-bound.
* **Error handling** – disconnect ⇒ opponent wins by forfeit; malformed frame ⇒ `PacketType.ERROR`.

### 13.2 Client responsibilities
* Human-facing CLI: render two ASCII grids, parse `/chat` and standard commands.
* Maintain *local* view only – trusts every ruling from the server.
* Background receiver thread decodes framed or legacy lines and updates the UI in real time.

### 13.3 Communication protocol
* Default line-oriented legacy messages for backward compatibility.
* Tier 4 adds a 16-byte header + JSON payload (`common.py`).
* Optional AES-CTR encrypts *payload bytes* only; header (incl. CRC-32) stays clear-text.

### 13.4 Determinism & testing
* Strict turn-prompting guarantees only one legal action at any time → reproducible runs.
* Unit tests cover rules; integration tests spin an actual server & two sockets under `pytest`.

---

## 14 Lines-of-Code Budget & Minimisation Tactics

Staying below **2 000 production LOC** is a hard rubric gate. Current count ≈ 1 450. Key tactics:

| Principle | Example |
|-----------|---------|
| **DRY** – no duplication | `common.parse_coord()` reused by server & client |
| **Pythonic primitives** | `all(ship.sunk for ship in ships)` replaces verbose loops |
| **Std-lib first** | `queue.Queue`, `enum.Enum`, `threading` keep deps light |
| **Focused helpers** | `broadcast_result()` centralises dual-socket messaging |
| **Lean protocol** | Text + tiny JSON → no heavyweight serializers |
| **Essential comments only** | Deep explanations live in this README, not inline |
| **Early testing** | Prevents last-minute patch-bloat |

With these guardrails we have ~ 500 LOC headroom for the remaining secure-flag work and any bug-fixes.

---
