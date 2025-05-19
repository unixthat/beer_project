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

## T4.1 Custom Low-Level Protocol with CRC-32

### Packet Structure
| Offset | Field          | Size  | Description                                 |
|:------:|----------------|:-----:|---------------------------------------------|
| 0–1    | `magic`        | 2 B   | Fixed 0xBEEF                                |
| 2      | `version`      | 1 B   | Protocol version (1)                        |
| 3      | `ptype`        | 1 B   | PacketType enum (GAME=0, CHAT=1, …)         |
| 4–7    | `seq`          | 4 B   | Monotonic u32 BE, also used as CTR nonce    |
| 8–11   | `length`       | 4 B   | Payload length in bytes                     |
| 12–15  | `crc32`        | 4 B   | CRC-32 over (header[0:12] + payload)        |
| 16–   | `payload`      | N B   | JSON-encoded UTF-8 object                   |

### Implementation Highlights
- **Framing** and **unframing** in `src/beer/common.py`:
  - `_HEADER_STRUCT = struct.Struct(">HBBII")`, `HEADER_LEN = 16 + 4`
  - `pack(ptype, seq, obj)` → dump JSON → _(encrypt?)_ → header + crc + payload
  - `unpack(stream)` → read header → validate magic/version → read payload → check CRC → _(decrypt?)_ → parse JSON
- **Checksum**
  - CRC-32 via `zlib.crc32(...)&0xFFFFFFFF`
  - Covers both header bytes 0–11 and the (optional encrypted) payload
- **Error policy & reliability**
  - On magic/version mismatch or CRC failure → `CrcError(seq)` → receiver sends `NAK(seq)` and discards frame
  - On successful frame → receiver sends `ACK(seq)` immediately
  - On premature close → `IncompleteError` → clean exit

### Reliability (ACK/NAK & Sliding Window)

- **Control frames**: PacketType.ACK (2) and PacketType.NAK (3), zero-length JSON payloads carrying `seq`.
- **Retransmit buffer**: `send_pkt` keeps a circular buffer of the last *W* = 32 raw frames per connection.
- **Sender control loop**: background thread reading ACK/NAK from peer; on `ACK(seq)` prunes that entry, on `NAK(seq)` looks up and resends raw bytes.
- **Receiver behavior**: after `unpack()`, send `ACK(seq)`; on CRC mismatch catch `CrcError` and send `NAK(seq)`.
- **Window management**: discard buffer entries older than *W*; out-of-order or missing packets trigger NAK for that `seq`.

### Error-Injection Tests

In `tests/test_checksum_recovery.py`, we inject bit-flips into some frames at a controlled rate (e.g. 1%), then drive a client/server echo exchange:
1. Count how many NAKs and retransmissions occur; ensure all data arrives in correct order.
2. Verify that the observed CRC failures ≈ injection rate.
3. Assert retransmissions ≤ *buffer_size*×error_rate.

────────────────────────────────────────────────────────

## T4.3 Encryption Layer (AES-CTR)

### Algorithm & Integration
- **Cipher**: AES in CTR mode (via `cryptography.hazmat`)
- **Key**: 16/24/32-byte key provided out-of-band (CLI `--secure[=<hex>]` or env `BEER_KEY`)
- **Nonce/IV**: 16 bytes = 8 byte big-endian `seq` + 8 zero bytes
- **Flow**:
  1. JSON payload → UTF-8 bytes
  2. **Encrypt** payload with AES-CTR(nonce) if `_SECRET_KEY` set
  3. Compute CRC-32 over header + encrypted payload
  4. Send header + CRC + encrypted payload
  5. Receiver reads, checks CRC, then **decrypts**, then JSON-parse

### Replay & IV Management
- **Uniqueness** guaranteed as long as `seq` increments monotonically per-stream
- No explicit replay detection: receiver will happily decrypt and accept any valid CRC frame
- **Future enhancement**: track last-seen `seq` and drop duplicates

### Partial Corruption
- **CRC mismatch** → `CrcError` → disconnect
- No in-protocol recovery

### Key Exchange & Assumptions
- **Out-of-band** key distribution only
- No Diffie-Hellman or KEM in the protocol
- Suitable for demo/enforced LAN scenarios

────────────────────────────────────────────────────────
