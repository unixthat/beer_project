"""Low-level packet framing utilities (Tier 4.1).

Frame layout (16-byte header + JSON payload):
0-1  : 0xBE ER      magic bytes
2    : version (1)
3    : PacketType (enum)
4-7  : seq u32 (big-endian)
8-11 : len u32 (payload length)
12-15: CRC-32 over header[0:12]+payload
16-  : UTF-8 JSON payload

Control frames:
- ACK: PacketType.ACK with zero-length JSON payload; seq indicates acknowledged packet.
- NAK: PacketType.NAK with zero-length JSON payload; seq indicates packet requested for retransmission.
"""

from __future__ import annotations

import enum
import json
import struct
import zlib
from io import BufferedReader, BufferedWriter
from typing import Any, Final, Tuple
import weakref
from collections import OrderedDict

from . import config as _cfg

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
except ImportError:  # pragma: no cover – crypto optional
    Cipher = None  # type: ignore

MAGIC: Final[int] = 0xBEEF  # 2-byte magic; spec says 0xBEER (not valid hex)
VERSION: Final[int] = 1
_HEADER_STRUCT = struct.Struct(">HBBII")  # magic(2) ver(1) type(1) seq(4) len(4)
HEADER_LEN = _HEADER_STRUCT.size + 4  # +CRC32

_SECRET_KEY: bytes | None = None

DEFAULT_KEY = _cfg.DEFAULT_KEY

# Retransmit buffer: map each BufferedWriter to its recent {seq: raw_bytes}
SEND_BUFFER_WINDOW = 32
_send_buffers: weakref.WeakKeyDictionary[BufferedWriter, OrderedDict[int, bytes]] = weakref.WeakKeyDictionary()


def enable_encryption(key: bytes) -> None:
    """Enable AES-CTR encryption for payload bytes (16-byte key)."""
    global _SECRET_KEY
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16/24/32 bytes")
    if Cipher is None:
        raise RuntimeError("cryptography not installed; cannot enable encryption")
    _SECRET_KEY = key


class PacketType(int, enum.Enum):
    """Enumerate BEER wire-protocol packet categories, including reliability control frames."""

    GAME = 0
    CHAT = 1
    ACK = 2  # Acknowledgement: seq carries the acknowledged packet number
    NAK = 3  # Negative-ack: request retransmission of seq number
    OPP_GRID = 4


class FrameError(Exception):
    """Base for framing problems."""


class CrcError(FrameError):
    """Raised when a CRC-32 check fails while decoding a frame, carrying the seq number."""

    def __init__(self, seq: int):
        super().__init__(f"CRC mismatch for seq {seq}")
        self.seq = seq


class IncompleteError(FrameError):
    """Raised when the stream closes before a full frame could be read."""


# ---------------------------------------------------------------------------
# Packing / unpacking helpers
# ---------------------------------------------------------------------------


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def pack(ptype: PacketType, seq: int, obj: Any) -> bytes:
    """Serialize *obj* into a framed BEER packet.

    Args:
        ptype: PacketType describing the logical payload.
        seq:   Monotonic per-stream sequence number (u32), reused as CTR nonce.
        obj:   JSON-serialisable Python object to embed as payload.

    Returns:
        Raw bytes ready to send on the wire (header + CRC + payload).
    """
    payload = json.dumps(obj, separators=(",", ":")).encode()
    if _SECRET_KEY is not None and Cipher is not None:
        nonce = struct.pack(">Q", seq) + b"\0" * 8  # 16-byte CTR IV
        cipher = Cipher(algorithms.AES(_SECRET_KEY), modes.CTR(nonce), backend=default_backend())
        payload = cipher.encryptor().update(payload)
    header_no_crc = _HEADER_STRUCT.pack(MAGIC, VERSION, ptype.value, seq, len(payload))
    crc = _crc32(header_no_crc + payload)
    return header_no_crc + struct.pack(">I", crc) + payload


def _unpack_header(buf: bytes) -> Tuple[int, int, int, int, int]:
    magic, ver, ptype, seq, length = _HEADER_STRUCT.unpack(buf)
    return magic, ver, ptype, seq, length


def unpack(stream: BufferedReader) -> Tuple[PacketType, int, Any]:
    """Read one framed packet from *stream* and return (ptype, seq, obj)."""
    # Read fixed header
    hdr = stream.read(HEADER_LEN)
    if len(hdr) < HEADER_LEN:
        raise IncompleteError("stream closed while reading header")
    magic, ver, ptype_byte, seq, length = _unpack_header(hdr[:-4])
    crc_expected = struct.unpack(">I", hdr[-4:])[0]
    if magic != MAGIC or ver != VERSION:
        raise FrameError("magic/version mismatch")
    payload = stream.read(length)
    if len(payload) < length:
        raise IncompleteError("stream closed while reading payload")
    crc_actual = _crc32(hdr[:-4] + payload)
    if crc_actual != crc_expected:
        # Sequence number is known from header
        raise CrcError(seq)
    if _SECRET_KEY is not None and Cipher is not None:
        nonce = struct.pack(">Q", seq) + b"\0" * 8
        cipher = Cipher(algorithms.AES(_SECRET_KEY), modes.CTR(nonce), backend=default_backend())
        payload = cipher.decryptor().update(payload)
    obj = json.loads(payload.decode()) if payload else None
    return PacketType(ptype_byte), seq, obj


# ---------------------------------------------------------------------------
# Convenience wrappers for file-like objects
# ---------------------------------------------------------------------------


def send_pkt(w: BufferedWriter, ptype: PacketType, seq: int, obj: Any) -> None:
    """Write a single framed packet to buffered writer *w* and flush."""
    # Prepare frame
    raw = pack(ptype, seq, obj)
    # Stash for possible retransmission
    buf = _send_buffers.get(w)
    if buf is None:
        buf = OrderedDict()
        _send_buffers[w] = buf
    buf[seq] = raw
    # Prune old entries beyond window
    while len(buf) > SEND_BUFFER_WINDOW:
        buf.popitem(last=False)
    # Send on the wire
    w.write(raw)
    w.flush()


def recv_pkt(r: BufferedReader) -> Tuple[PacketType, int, Any]:
    """Blocking helper that returns the next `(ptype, seq, obj)` tuple from *r*."""
    return unpack(r)


# Public helpers ----------------------------------------------------------------

__all__ = [
    "PacketType",
    "enable_encryption",
    "pack",
    "unpack",
    "send_pkt",
    "recv_pkt",
    "handle_control_frame",
]


def handle_control_frame(w: BufferedWriter, ptype: PacketType, seq: int) -> None:
    """Process ACK/NAK frames on writer *w*: prune on ACK, retransmit on NAK."""
    buf = _send_buffers.get(w)
    if not buf:
        return
    if ptype == PacketType.ACK:
        # Acknowledged, remove from buffer
        buf.pop(seq, None)
    elif ptype == PacketType.NAK:
        # Retransmit this packet if we have it
        data = buf.get(seq)
        if data:
            w.write(data)
            w.flush()
