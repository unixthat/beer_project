# BEER – Battleships: Engage in Explosive Rivalry
High-Distinction Implementation Plan  (2025-05-16)

---

## TL;DR
A modern Python 3.11 code-base that delivers the full four-tier BEER specification on **< 1 600 LOC** (production).
Key pillars:

* **src/beer/** installable package – no legacy top-level scripts.
* **Central `config.py`** – _all_ env-tunable constants live here.
* **Event → Packet → UI** messaging pipeline – zero ad-hoc prints; debug toggle via `--debug` / `BEER_DEBUG=1`.
* **Thread-per-socket** lobby server capable of spectators & reconnect.
* Quality gates: **Black 24.x + Flake8 7.x + Mypy --strict + pytest 8.x coverage ≥ 90 %**.
* Multi-arch Docker image (`python:3.11-slim`) for reproducible runs on amd64/arm64.

---

## 1 Tech Stack
| Area | Choice | Rationale |
|------|--------|-----------|
| Language | Python 3.11 | batteries-included std-lib, type-hints, *threading* |
| Net Protocol | 16-byte header + JSON payload (+ AES-CTR opt-in) | Tier 4.1 & 4.2 |
| Concurrency | Thread-per-socket | simple & portable; I/O-bound game |
| Container | python:3.11-slim multi-arch | identical behaviour on Apple Silicon & x86_64 |
| Tooling | Black 24.x, Flake8 7.x, Mypy 1.10, Pytest 8.x | enforced via pre-commit & CI |

---

## 2 Directory Layout (current)
```
.
├── pyproject.toml                 # build metadata
├── src/beer/
│   ├── __init__.py               # package export list
│   ├── config.py                 # **single source of env config**
│   ├── common.py                 # framing, CRC-32, AES helpers
│   ├── battleship.py             # rules engine (imports constants from config)
│   ├── session.py                # GameSession – emits Event objects
│   ├── server.py                 # lobby, accepts sockets, translates Events → Packets
│   ├── client.py                 # human CLI (Packet → UI)
│   ├── bot_logic.py              # parity-hunt AI
│   └── bot.py                    # network wrapper, `python -m beer.bot`
└── tests/
    ├── tier1/ … tier4/           # tiered integration tests
    └── unit/                     # pure logic tests
```

---

## 3 Configuration & Env-Vars
All runtime knobs are defined once in `src/beer/config.py`.

| Env Var | Constant | Purpose | Default |
|---------|----------|---------|---------|
| `BEER_HOST` | `DEFAULT_HOST` | Server bind / client connect host | 127.0.0.1 |
| `BEER_PORT` | `DEFAULT_PORT` | TCP port | 5000 |
| `BEER_TURN_TIMEOUT` | `TURN_TIMEOUT` | Seconds player may idle | 180 |
| `BEER_PLACE_TIMEOUT` | `PLACEMENT_TIMEOUT` | Manual placement prompt | 30 |
| `BEER_BOT_DELAY` | `BOT_LOOP_DELAY` | Sleep per bot loop | 0 |
| `BEER_SERVER_POLL_DELAY` | `SERVER_POLL_DELAY` | Non-turn poll sleep | 0 |
| `BEER_SIMPLE_BOT` | `SIMPLE_BOT` | Force simple parity AI | 0 |
| `BEER_KEY` | `DEFAULT_KEY` | AES key (hex) | demo key |
| `BEER_BOARD_SIZE` | `BOARD_SIZE` | Board dimension | 10 |
| `BEER_DEBUG` | – | Enable python-logging DEBUG in any component | 0 |

Guideline: **never** call `os.getenv()` outside `config.py`.

---

## 4 Messaging Architecture (Tier -HD upgrade)
```
Session (game logic)   →  Event(category, subtype, payload)
Server (transport)     →  PacketType.GAME | CHAT | ERROR
Client/Bot (UI/AI)     →  print / update / AI decision
```
* Each turn produces ≤ 3 Events: `turn.start`, `turn.shot`, `turn.end`.
* Server subscribes, serialises to framed packets (`common.py.pack`).
* `--debug` flag enables python-logging of Events on both server & client.

Outcome: deterministic tests, easy spectator / chat tweaks, minimal string duplication.

---

## 5 Road-map Snapshot (concise)
| ID | Area | Status |
|----|------|--------|
| 1-4 | Tier-1 core + features | 🟢 merged |
| 5 | Graceful shutdown | 🟡 planned |
| 6 | Reconnect-spectator bug | 🟡 known issue |
| 7 | Chat robustness | 🟡 verify/fix |
| 8 | Docs refresh | 🟡 todo |
| 9 | CI quality gates | 🟡 pipeline work |
| 10 | Cursor rules | 🟡 polish |
| 11 | Tiered tests | 🟡 continue filling gaps |
| 12 | Messaging refactor | 🔴 **current focus** |

---

## 6 Run & Test Cheatsheet
```bash
# Dev
python -m venv venv && . venv/bin/activate
pip install -e .[dev]
python -m beer.server --debug  # server with DEBUG logs
python -m beer.bot -v          # two bots in separate shells

# Encrypted demo
python -m beer.server --secure --port 5001
python -m beer.client --secure --port 5001

# Docker
docker compose up --build --scale bot=2

# Tests & quality
pytest -q
ython -m black --check .
flake8 src tests
mypy --strict src
```

---

## 7 LOC Budget
Running `cloc $(git ls-files 'src/beer/*.py')` currently reports **≈ 1 350 LOC** – safe margin under 2 000.

---

## 8 Milestones to HD
1. **Finish Messaging Refactor (ID-12)** <- _in progress_
2. **Graceful Shutdown** (ID-5)
3. **Reconnect fix** (ID-6)
4. Final CI pipeline and docs polish.

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
| ✅ | **Replay-attack proof-of-concept** (`
