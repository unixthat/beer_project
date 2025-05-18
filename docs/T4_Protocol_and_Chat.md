# Tier 4 Deliverables — Chat, Custom Protocol & Encryption

This document summarizes our Tier 4.1–4.3 implementations: the in-game chat channel (T4.2), our custom low-level framed protocol with CRC-32 checksum (T4.1), and the AES-CTR encryption layer (T4.3).

────────────────────────────────────────────────────────

## T4.2 Chat Functionality

• **Wire format**
  – PacketType: `CHAT` (enum value 1)
  – JSON payload: `{"type":"chat","name":"P<1|2>","msg":"…"}`

• **Client**
  – Supports `/chat <text>` (case-insensitive) alias in its prompt loop
  – Parses incoming `PacketType.CHAT` frames and invokes `h_chat()`, printing `[CHAT] P#: <msg>`

• **Server**
  – In `recv_turn()`, `ChatCommand` from attacker or defender is routed via `io_utils.chat_broadcast`.
  – We patched `session.recv_turn` so that after `chat_broadcast` to the two players, we also call `session._broadcast(...)` to stream chat to any waiting spectators.
  – End-to-end coverage in `tests/test_chat_spectator.py`:
    1. Player 1's chat → visible to Player 2 & spectator
    2. Player 2's chat → visible to Player 1 & spectator
    3. Spectator input → ignored by both players

────────────────────────────────────────────────────────

## T4.1 Custom Low-Level AEAD Framing

### AEAD Packet Structure
| Offset | Field        | Size  | Description                                       |
|:------:|--------------|:-----:|---------------------------------------------------|
| 0–1    | `magic`      | 2 B   | Fixed value 0xBEEF                                |
| 2      | `version`    | 1 B   | Protocol version (1)                              |
| 3      | `ptype`      | 1 B   | PacketType enum (GAME=0, CHAT=1, …)               |
| 4–7    | `seq`        | 4 B   | Monotonic u32 BE (sequence number)                |
| 8–19   | `nonce`      | 12 B  | Random IV/nonce for AES-GCM                       |
| 20–23  | `length`     | 4 B   | Ciphertext+tag length (bytes)                     |
| 24–   | `data`       | N B   | AES-GCM ciphertext (N-16) + 16 B authentication tag|

### Implementation Highlights
- AEAD framing/unframing is handled in `src/beer/encryption.py` and delegated from `common.py`.
- Header is defined by `Struct(">HBBI12sI")`, constants in `encryption.HEADER_STRUCT`.
- `pack(ptype, seq, payload)` → JSON→bytes → AES-GCM encrypt → header + ciphertext + tag.
- `unpack(frame)` → parse header → decrypt ciphertext+tag → JSON parse.
- Integrity & authenticity via AES-GCM; no separate CRC needed.
- Replay & order: `common.recv_pkt` uses per-stream `ReplayWindow` to drop old or duplicated seqs.

────────────────────────────────────────────────────────

## T4.3 Encryption Layer (AES-CTR)

### Algorithm & Integration
- **Cipher**: AES-GCM (AEAD) via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
- **Key**: 16/24/32-byte key from out-of-band (`--secure` flag or `BEER_KEY` env).
- **Nonce/IV**: 12 random bytes per-packet via `os.urandom(12)`.
- **Flow**:
  1. JSON payload → UTF-8 bytes
  2. **Encrypt** payload → AES-GCM ciphertext + 16 B tag
  3. Build header (magic, version, ptype, seq, nonce, length)
  4. Transmit header + ciphertext+tag
  5. Receiver reads, decrypts/authenticates via AES-GCM, then JSON parse.

### Replay, Order & Rekeying
- **Replay protection**: per-stream `ReplayWindow` drops any `seq` ≤ highest seen, allows limited out-of-order within a window size.
- **Out-of-order**: frames with `seq` > highest-window_size are accepted and buffered.
- **Rekeying**: stubbed auto-rekey after packet/time thresholds; ECDH handshake in `src/beer/keyexchange.py` enables future key rotation.

### Partial Corruption & Authentication
- **Tampering** on ciphertext or auth tag → decrypt fails (`InvalidTag`) → frame dropped or disconnect.
- **Header errors** (magic/version mismatch) → `FrameError`.

### Key Exchange & Assumptions
- **Key exchange** via ECDH handshake stubs in `keyexchange.py` (client_hello/server_hello + HKDF).
- **Handshake** messages sent in clear-text before framing to derive per-session AES-GCM keys.
- Clients send `HELLO <pubA>`, server replies `HELLO <pubB>`, derive `session_key = HKDF(pubA||pubB)`.
- Current implementation assumes static key by default; handshake optional if invoked.

────────────────────────────────────────────────────────
