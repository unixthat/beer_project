# BEER Battleship — Comprehensive Project Report
Stephen Beaver (ID 10423362) · Daniyal Qureshi (ID 23976415)  
Demo video: *[insert URL]*

## 1 Introduction

### 1.1 Context & Motivation
The **BEER** project re‑imagines the classic two‑player Battleship game as a real‑time, networked application.  
Its aim is to give students hands‑on experience with client–server communication, concurrency, reliability and security challenges that are glossed over in typical turn‑based coursework.

### 1.2 Objectives & Scope
We set out to build a Python‑based system that

* delivers fluid, low‑latency two‑player matches over TCP;
* scales to multiple concurrent games without restarting the server;
* survives transient disconnects and allows spectators;
* provides an in‑game instant‑messaging (IM) channel; and
* protects data integrity and confidentiality with a custom framed protocol, checksums and optional encryption.

## 2 BEER Overview

### 2.1 Gameplay
Players secretly position a fleet on a 10 × 10 grid (or 5 × 5 in one‑ship mode) and alternate firing shots.  
The server replies with **HIT**, **MISS**, **SUNK <ship>** or **ALREADY_SHOT** until one fleet is destroyed.

### 2.2 System Architecture
| Component          | Responsibility                                                                                                        |
|--------------------|------------------------------------------------------------------------------------------------------------------------|
| **Server**         | Maintains authoritative game state; accepts TCP connections; matches players; validates commands; broadcasts updates. |
| **Client**         | Sends user commands; renders board and chat; captures user input in a non‑blocking thread.                             |
| **Protocol layer** | Frames, checksums and (optionally) encrypts every packet (see § 4).                                                    |

Threads keep network I/O separate from gameplay on both ends, preventing stalls while keeping the code largely synchronous.

## 3 Tiered Implementation Summary

| Tier | Key Features Delivered                                                                                | Design Highlights                                                                                                |
|------|--------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| **1** | Two‑player matches; basic concurrency                                                                 | Separate threads for user input vs. server messages prevent prompt corruption.                                   |
| **2** | Robust validation, multiple games per run, timeouts, lobby                                            | *LobbyManager* queues excess clients; idle sockets are reaped; out‑of‑bounds and duplicate shots rejected.       |
| **3** | Spectators, seamless match rotation, groundwork for reconnection                                      | Spectators receive all broadcasts but cannot act; finished players are cycled out without restarting the server. |
| **4** | Custom framed protocol with CRC‑32, reliable ACK/NAK window, IM channel, optional AES‑CTR encryption  | Detailed in § 4.                                                                                                 |

## 4 Advanced Protocol & Communication (Tier 4)

### 4.1 Custom Framed Protocol with CRC‑32

| Offset | Field     | Bytes | Purpose                                    |
|:------:|-----------|:-----:|--------------------------------------------|
| 0–1    | `magic`   | 2     | Constant **0xBEEF** guard                  |
| 2      | `version` | 1     | Current protocol = 1                       |
| 3      | `ptype`   | 1     | `GAME`, `CHAT`, `ACK`, `NAK`, …            |
| 4–7    | `seq`     | 4     | Monotonic sequence; also used as CTR nonce |
| 8–11   | `length`  | 4     | Payload size                               |
| 12–15  | `crc32`   | 4     | CRC‑32 over header 0–11 + payload          |
| 16–    | `payload` |  N    | JSON (optionally encrypted)                |

* **Integrity** – CRC‑32 detects corruption before JSON parsing.  
* **Reliability** – `ACK`/`NAK` frames and a 32‑slot retransmit buffer form a sliding‑window resend strategy.  
* **Thread safety** – Send/receive locks prevent interleaved frames when multiple client threads share a socket.

### 4.2 Instant‑Messaging Channel
`PacketType.CHAT` carries JSON like `{"type":"chat","name":"P1","msg":"…"}`.

* **Client UX** – `/chat <text>` sends a chat frame; incoming chat is printed with a `[CHAT]` prefix.  
* **Server routing** – `io_utils.chat_broadcast()` forwards chat to both players and spectators without blocking turn logic.  
* **Security** – Chat frames obey the same CRC‑32 and optional AES encryption as game frames, preventing spoofing or tampering.

### 4.3 AES‑CTR Encryption (Optional)
* **Cipher** – AES‑CTR via *cryptography* library.  
* **Key distribution** – Out‑of‑band (`--secure <hex‑key>`).  
* **Nonce** – 16 B = 8 B big‑endian `seq` + 8 B zero pad.  
* **Flow** – Encrypt payload → compute CRC → transmit; receiver verifies CRC then decrypts.

> **Reconnection (Tier 4.3)** is partially implemented: session‑mapping structures exist, but reliable restoration of a live match is unfinished.

## 5 Security Analysis & Mitigations

| Threat                               | Risk                                           | Counter‑Measures                                           |
|--------------------------------------|------------------------------------------------|------------------------------------------------------------|
| **Session hijack / impersonation**   | Attacker replays `CONNECT` to take a seat      | Username uniqueness at handshake; sequence‑number checks.  |
| **Replay attacks**                   | Re‑send old `FIRE` to repeat moves             | Monotonic `seq`; 5 s timestamp window.                     |
| **Packet tampering**                 | Modify coordinates in flight                   | CRC‑32 over header & payload; receiver sends `NAK`.        |
| **Eavesdropping**                    | Read chat or board state                       | AES‑CTR encryption when `--secure` key provided.           |
| **DoS via malformed frames**         | Crash parser                                   | Magic/version guards; length sanity; invalid frames drop.  |

## 6 Testing & Evaluation

1. **Checksum recovery** – Bit‑flip injection at 1 % proves `NAK`/retransmit restores order with zero corruption.  
2. **Chat coverage** – Unit tests verify every chat permutation reaches intended recipients and spectators ignore their own sends.  
3. **Load & concurrency** – CI script launches 50 client threads; server completes 100 % of matches without deadlocks.

### About asyncio

A full asyncio rewrite was attempted early in development but quickly **ballooned past 6 000 LoC** while still exhibiting elusive race conditions.  
For a LAN‑only text game with two local clients and a local server, **Python threads (plus locks) are more than sufficient** and keep the codebase approachable (~2 100 LoC).  
Should BEER ever target thousands of concurrent Internet games, revisiting an event‑driven model would be worthwhile—but for this scope threading wins on effort‑to‑benefit ratio.

## 7 Challenges & Future Work

* **Thread‑safe reconnection** – needs persistence or an async rewrite to resume games safely.  
* **Key exchange** – integrate Diffie–Hellman to remove the out‑of‑band key.  
* **Spectator controls** – allow filtering of chat/board for large audiences.  
* **Performance** – investigate `trio` or low‑overhead async frameworks if scaling beyond LAN.

## 8 Conclusion

The project now delivers a feature‑complete networked Battleship experience across four implementation tiers.  
By designing a bespoke framed protocol with reliability and optional encryption—and by adding a chat channel—we move beyond toy coursework toward a robust mini online service.  
Remaining gaps (reconnection, key exchange) are incremental improvements rather than architectural rewrites.

## 9 Installation & Development Guide

### 9.1 Prerequisites
* **Python 3.11**
* A POSIX‑like shell (or PowerShell on Windows).

### 9.2 Quick Start

```bash
# Clone code and enter folder
git clone <repo‑url>
cd beer-battleship

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install BEER *and* all dev tools in editable mode
python -m pip install --upgrade pip
pip install -e .  # editable install, exposes 'beer-server', 'beer-client', 'beer-bot' CLIs
pip install black==24.4.2 flake8==7.0.0 mypy==1.10.0 pytest==8.2.0 pytest-timeout==2.3.1 \
    pre-commit==3.7.0 cryptography==42.0.5 docstr-coverage==2.2.0 pytest-cov
```

### 9.3 Running a Game

```bash
# Terminal 1 – start server
beer-server

# Terminal 2 – player 1
beer-client --name Alice

# Terminal 3 – player 2
beer-client --name Bob
```

### 9.4 Testing

```bash
pytest  # runs all unit & integration tests
```

### 9.5 Packaging Metadata (`pyproject.toml` excerpt)

```toml
[project]
name = "beer-battleship"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
beer-server = "beer.server:main"
beer-client = "beer.client:main"
beer-bot    = "beer.bot:main"

[tool.black]
line-length = 120
target-version = ["py311"]
```
