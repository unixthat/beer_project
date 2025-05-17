# Final Road‑map – BEER Server Refactor
*Issued 17 May 2025 (AWST)*

---

## Executive summary
`session.py` is now **292 logical lines**, comfortably under the 320‑line ceiling.
The helper split is complete, **but ten functional gaps remain** (queue‑policy, CRC‑32 enforcement, token‑collision defence, etc.).
This roadmap lists every open issue, pending file‑cleanup, and the micro‑refactor still required for full RULES v3 and Tier‑4 compliance.

---

## 1 · Critical functional gaps

| ID | Problem | Fix location | Rule / tier |
|----|---------|--------------|-------------|
| **G‑1** | Winner/loser re‑queue order wrong. | `server._monitor_session()` | § 7 queue rules |
| **G‑2** | Duplicate PID‑token attach accepted silently. | `reconnect_controller.attach_player` | E‑5 |
| **G‑3** | Residual “TOKEN …” line leaks into first read after reconnect. | `attach_player()` | E‑4 |
| **G‑4** | Simultaneous double‑drop handled as single wait. | `session.py` poll‑loop | E‑1 |
| **G‑5** | When a promoted spectator disconnects (or fails reconnection) before taking a turn, session.py must call spectator_hub.promote(slot, session) again until either (a) a connected spectator fills the slot or (b) the queue is empty, in which case drop_and_deregister(slot,"timeout") triggers and the opponent wins.
| **G‑6** | Wizard timeout not reset **per ship**. | `placement_wizard.run` | E‑3 |
| **G‑7** | Timeout/quit logic duplicated. | add `drop_and_deregister()` | § 8 |
| **G‑8** | Spectator commands return generic `ERR`. | `io_utils.recv_turn` | E‑6 |
| **G‑9** | Winner socket re‑queued even when already dead. | `_monitor_session()` | E‑7 |
| **G‑10** | AES/HMAC layer still disabled ⇒ Tier‑4 only 1 / 2 met. | `server.py` (enable flag) | T4‑3/4 |

---

## 2 · Protocol / framing upgrades

* Add **CRC‑32**: `zlib.crc32(data)` and append 4‑byte big‑endian checksumciteturn0search0.
* Verify checksum in `recv_pkt()`; after **three** failures reply `ERR BAD_CSUM` then call `drop_and_deregister()`citeturn0search6.
* When AES‑CTR is enabled, compute the CRC on the *cipher‑text* so integrity covers encrypted bytesciteturn0search1.

---

## 3 · File inventory & actions

| File | Keep? | Action |
|------|-------|--------|
| **`bot_logic.py`** & friends | dev‑only | move to `tests/` |
| **`game.py`** | ❌ | delete – empty shim |
| **`router.py`** | ⚠ | fold minimal `EventRouter` into `server.py` |
| **`commands.py`** | ❌ | delete – superseded by `io_utils.recv_turn` |
| **`io_utils.py`** | split | create `framing.py` (CRC/encrypt/HMAC) |
| **`gym_beer_env.py`** | keep | mark as optional RL wrapper |

---

## 4 · Micro‑refactor plan

1. **`framing.py`**
   ```python
   def pack(ptype, seq, payload): ...
   def unpack(buff): ...
   ```
   Handles length + JSON + CRC‑32 (+ AES/HMAC).
2. **`queue.py`** – wrapper around `collections.deque` with `insert_head`, `append_tail`, `pop_pair` for O(1) queue opsciteturn0search2.
3. **`chat.py`** – `broadcast(idx, txt, session)` and spectator‑command guard (fix G‑8).
4. Central **`drop_and_deregister(slot, reason)`** helper (fix G‑7).
5. Enable AES‑CTR with optional HMAC flag in `server.py` (completes Tier‑4).

---

## 5 · Tier‑4 status after patches

| Feature | State |
|---------|-------|
| CRC‑32 framing | **✓ once framing.py lands** |
| Advanced chat | ✓ already |
| Encryption (AES‑CTR) | ✓ once flag enabledciteturn0search4 |
| HMAC / nonce | optional extra‑credit |

---

## 6 · Milestone checklist

1. **Fix G‑1 … G‑4** (critical queue & reconnect)
2. **framing.py + CRC‑32**
3. `drop_and_deregister()` + wizard timeout reset (G‑6, G‑7)
4. Spectator guard & second promotion (G‑5, G‑8)
5. AES flag + winner‑socket check (G‑9, G‑10)
6. Delete legacy files & split helpers

All six milestones green ⇒ full RULES v3 + Tier‑4 compliance.

---

## 7 · Useful references

1. Official Python docs for `zlib.crc32` – usage & signatureciteturn0search0
2. PyCryptodome AES‑CTR example – encrypt/decrypt boiler‑plateciteturn0search1
3. Real Python guide to efficient `deque` operations – queue helper patternsciteturn0search2
