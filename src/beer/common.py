"""Low-level packet framing utilities (Tier 4.1).

Frame layout (16-byte header + JSON payload):
0-1  : 0xBE ER      magic bytes
2    : version (1)
3    : PacketType (enum)
4-7  : seq u32 (big-endian)
8-11 : len u32 (payload length)
12-15: CRC-32 over header[0:12]+payload
16-  : UTF-8 JSON payload
"""

from __future__ import annotations

import enum
import json
from io import BufferedReader, BufferedWriter
from typing import Any, Final, Tuple

from . import config as _cfg
from .replay import ReplayWindow
from .reliability import RetransmissionBuffer
from .encryption import HEADER_STRUCT as AEAD_HEADER_STRUCT, pack as aead_pack, unpack as aead_unpack
from cryptography.exceptions import InvalidTag

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
except ImportError:  # pragma: no cover – crypto optional
    Cipher = None  # type: ignore

MAGIC: Final[int] = 0xBEEF  # 2-byte magic; spec says 0xBEER (not valid hex)
VERSION: Final[int] = 1

# Encryption flag (unused in legacy framing)
_SECRET_KEY: bytes | None = None

# Default AES key (for compatible calls to enable_encryption)
DEFAULT_KEY = _cfg.DEFAULT_KEY


def enable_encryption(key: bytes) -> None:
    """Set AES-CTR encryption key (no-op for legacy framing, accepted for compatibility)."""
    global _SECRET_KEY
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must be 16/24/32 bytes")
    _SECRET_KEY = key


def disable_encryption() -> None:
    """Disable AEAD encryption, reverting to legacy CRC framing."""
    global _SECRET_KEY
    _SECRET_KEY = None


class PacketType(int, enum.Enum):
    """Enumerate BEER wire-protocol packet categories."""

    GAME = 0
    CHAT = 1
    ACK = 2
    ERROR = 3
    OPP_GRID = 4
    NAK = 5  # negative acknowledgment for reliability
    REKEY = 6  # key-rotation handshake packet


class FrameError(Exception):
    """Base for framing problems."""


class CrcError(FrameError):
    """Raised when a CRC-32 check fails while decoding a frame."""


class IncompleteError(FrameError):
    """Raised when the stream closes before a full frame could be read."""


# ---------------------------------------------------------------------------
# AEAD vs CRC framing helpers
# ---------------------------------------------------------------------------

def _pack_aead(ptype_val: int, seq: int, payload: bytes) -> bytes:
    return aead_pack(ptype_val, seq, payload)

def _unpack_aead(frame: bytes) -> tuple[PacketType, int, Any]:
    magic2, version2, ptype2, seq2, plaintext = aead_unpack(frame)
    if magic2 != MAGIC or version2 != VERSION:
        raise FrameError("magic/version mismatch")
    try:
        obj = json.loads(plaintext)
    except Exception:
        obj = plaintext
    return PacketType(ptype2), seq2, obj


# ---------------------------------------------------------------------------
# Public pack / unpack
# ---------------------------------------------------------------------------

def pack(*args) -> bytes:
    """
    Serialize a BEER packet using AEAD framing for both JSON and raw-byte payloads.
    """
    if len(args) == 1 and isinstance(args[0], dict):
        pkt = args[0]
        ptype_val, seq, obj = int(pkt["ptype"]), pkt["seq"], pkt["obj"]
    elif len(args) == 3:
        ptype_val, seq, obj = int(args[0]), args[1], args[2]
    else:
        raise TypeError(f"Invalid pack signature: {args}")

    # Always use AEAD framing for payloads
    if isinstance(obj, (bytes, bytearray)):
        payload = obj
    else:
        payload = json.dumps(obj).encode()
    return _pack_aead(ptype_val, seq, payload)

def unpack(buf: bytes | BufferedReader) -> tuple[dict[str, Any], PacketType, int]:
    """
    Read one framed packet and return (pkt_dict, ptype, seq) using AEAD framing only.
    pkt_dict has keys 'ptype' (int), 'seq' (int), and 'obj' (payload bytes or JSON-decoded).
    """
    # Raw bytes AEAD path
    if isinstance(buf, (bytes, bytearray)):
        try:
            magic, version, pval, seq, plaintext = aead_unpack(buf)
        except InvalidTag:
            raise FrameError("AEAD authentication failed")
        if magic != MAGIC or version != VERSION:
            raise FrameError("magic/version mismatch")
        pkt = {'ptype': pval, 'seq': seq, 'obj': plaintext}
        return pkt, PacketType(pval), seq

    # File-like reader AEAD path via recv_pkt
    pkt_dict, ptype_enum, seq = recv_pkt(buf)  # type: ignore[arg-type]
    return pkt_dict, ptype_enum, seq


# ---------------------------------------------------------------------------
# Convenience wrappers for file-like objects
# ---------------------------------------------------------------------------


def send_pkt(w: BufferedWriter, ptype: PacketType, seq: int, obj: Any) -> None:
    """Write a single framed packet to buffered writer *w* and flush."""
    frame = pack(ptype, seq, obj)
    if not hasattr(w, "_retrans_buffer"):
        w._retrans_buffer = RetransmissionBuffer()
    w._retrans_buffer.add(seq, frame)
    w.write(frame)
    w.flush()


def recv_pkt(r: BufferedReader) -> Tuple[PacketType, int, Any]:
    """Blocking helper that returns the next `(ptype, seq, obj)` tuple from *r* using AEAD framing."""
    # Initialize replay window on this reader
    if not hasattr(r, "_replay_window"):
        r._replay_window = ReplayWindow()
    # Attach writer if provided (for NAK/ACK responses)
    writer = getattr(r, "_writer", None)

    from .encryption import complete_rekey
    from cryptography.exceptions import InvalidTag

    while True:
        # Read AEAD header
        header_len = AEAD_HEADER_STRUCT.size
        header = r.read(header_len)
        if len(header) < header_len:
            raise IncompleteError("Incomplete header")
        magic, version, ptype_val, seq, nonce, length = AEAD_HEADER_STRUCT.unpack(header)
        # Read ciphertext+tag
        ciphertext = r.read(length)
        if len(ciphertext) < length:
            raise IncompleteError("Incomplete payload")
        frame = header + ciphertext
        try:
            magic2, version2, ptype2, seq2, plaintext = aead_unpack(frame)
        except InvalidTag:
            # Authentication failure: request retransmission
            if writer is not None:
                send_pkt(writer, PacketType.NAK, seq, None)
            continue
        if magic2 != MAGIC or version2 != VERSION:
            raise FrameError("magic/version mismatch")
        # Rekey handshake
        if ptype2 == PacketType.REKEY.value:
            peer_pub = bytes.fromhex(plaintext.decode())
            complete_rekey(peer_pub)
            continue
        # Handle ACK: prune send buffer
        if ptype2 == PacketType.ACK.value:
            if writer is not None and hasattr(writer, "_retrans_buffer"):
                writer._retrans_buffer.ack(seq2)
            continue
        # Handle NAK: retransmit missing frame
        if ptype2 == PacketType.NAK.value:
            if writer is not None and hasattr(writer, "_retrans_buffer"):
                frame = writer._retrans_buffer.get(seq2)
                if frame is not None:
                    writer.write(frame)
                    writer.flush()
            continue
        # Replay protection: drop replayed or too-old sequences
        if not r._replay_window.validate(seq2):
            continue
        obj = json.loads(plaintext)
        return PacketType(ptype2), seq2, obj


# Public helpers ----------------------------------------------------------------

__all__ = [
    "PacketType",
    "enable_encryption",
    "disable_encryption",
    "pack",
    "unpack",
    "send_pkt",
    "recv_pkt",
]
