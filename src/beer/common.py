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
import struct
import zlib
from io import BufferedReader, BufferedWriter
from typing import Any, Final, Tuple

from . import config as _cfg
from .replay import ReplayWindow
from .reliability import RetransmissionBuffer
from .encryption import HEADER_STRUCT as AEAD_HEADER_STRUCT, pack as aead_pack, unpack as aead_unpack

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
except ImportError:  # pragma: no cover – crypto optional
    Cipher = None  # type: ignore

MAGIC: Final[int] = 0xBEEF  # 2-byte magic; spec says 0xBEER (not valid hex)
VERSION: Final[int] = 1
# Fixed header length: 2+1+1+4+4 (without CRC) + 4 CRC = 16 bytes
HEADER_LEN: Final[int] = 16

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


class PacketType(int, enum.Enum):
    """Enumerate BEER wire-protocol packet categories."""

    GAME = 0
    CHAT = 1
    ACK = 2
    NAK = 5  # negative acknowledgment for reliability
    ERROR = 3
    OPP_GRID = 4
    REKEY = 6  # key-rotation handshake packet


class FrameError(Exception):
    """Base for framing problems."""


class CrcError(FrameError):
    """Raised when a CRC-32 check fails while decoding a frame."""


class IncompleteError(FrameError):
    """Raised when the stream closes before a full frame could be read."""


# ---------------------------------------------------------------------------
# Packing / unpacking helpers
# ---------------------------------------------------------------------------


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def pack(*args) -> bytes:
    """Serialize a BEER packet.
    Under secure mode (encryption enabled), use AEAD for all payloads.
    Legacy CRC framing only when encryption is disabled and payload is not raw bytes.
    Supports signatures:
      pack({'ptype', 'seq', 'obj'}) or pack(ptype, seq, obj).
    """
    # Dict signature: supports raw-bytes under 'obj' or full dict JSON
    if len(args) == 1 and isinstance(args[0], dict):
        pkt = args[0]
        ptype_val = int(pkt['ptype'])
        seq = pkt['seq']
        obj = pkt['obj']
        # Raw bytes payload always AEAD
        if isinstance(obj, (bytes, bytearray)):
            return aead_pack(ptype_val, seq, obj)
        # Otherwise JSON encode full dict
        payload = json.dumps(pkt).encode()
        # Secure mode: AEAD framing
        if _SECRET_KEY is not None:
            return aead_pack(ptype_val, seq, payload)
        # Legacy JSON+CRC framing
        header = struct.pack(
            ">HBBII", MAGIC, VERSION, ptype_val, seq, len(payload)
        )
        crc = _crc32(header + payload)
        return header + struct.pack(
            ">I", crc
        ) + payload
    elif len(args) == 3:
        ptype_val = int(args[0])
        seq = args[1]
        obj = args[2]
        # Raw bytes payload always AEAD
        if isinstance(obj, (bytes, bytearray)):
            return aead_pack(ptype_val, seq, obj)
        # JSON payload
        payload = json.dumps(obj).encode()
        # Secure mode: AEAD framing
        if _SECRET_KEY is not None:
            return aead_pack(ptype_val, seq, payload)
        # Legacy JSON+CRC framing
        header = struct.pack(
            ">HBBII", MAGIC, VERSION, ptype_val, seq, len(payload)
        )
        crc = _crc32(header + payload)
        return header + struct.pack(
            ">I", crc
        ) + payload
    else:
        raise TypeError(f"Invalid pack signature: {args}")


def unpack(buf: bytes | BufferedReader) -> Tuple[PacketType, int, Any]:
    """Read one framed packet and return (ptype, seq, obj)."""
    # AEAD framing for raw-bytes input (always use AEAD for raw frames)
    from io import BytesIO
    if isinstance(buf, (bytes, bytearray)):
        reader = BytesIO(buf)
        # Read AEAD header
        header_len = AEAD_HEADER_STRUCT.size
        header_bytes = reader.read(header_len)
        if len(header_bytes) < header_len:
            raise IncompleteError("Incomplete header")
        magic, version, ptypeb, seqb, nonce, length = AEAD_HEADER_STRUCT.unpack(header_bytes)
        ciphertext = reader.read(length)
        if len(ciphertext) < length:
            raise IncompleteError("Incomplete payload")
        frame = header_bytes + ciphertext
        # Decrypt and unpack
        magic2, version2, ptype2f, seq2f, plaintext = aead_unpack(frame)
        if magic2 != MAGIC or version2 != VERSION:
            raise FrameError("magic/version mismatch")
        # Wrap raw plaintext in a packet dict
        pkt = {'obj': plaintext}
        return pkt, PacketType(ptype2f), seq2f
    # File-like input: choose AEAD or CRC based on encryption flag
    reader = buf
    if _SECRET_KEY is not None:
        # AEAD framing
        header_len = AEAD_HEADER_STRUCT.size
        header_bytes = reader.read(header_len)
        if len(header_bytes) < header_len:
            raise IncompleteError("Incomplete header")
        magic, version, ptype2, seq2, nonce, length = AEAD_HEADER_STRUCT.unpack(header_bytes)
        ciphertext = reader.read(length)
        if len(ciphertext) < length:
            raise IncompleteError("Incomplete payload")
        frame = header_bytes + ciphertext
        magic2, version2, ptype2f, seq2f, plaintext = aead_unpack(frame)
        if magic2 != MAGIC or version2 != VERSION:
            raise FrameError("magic/version mismatch")
        try:
            obj = json.loads(plaintext)
        except Exception:
            obj = plaintext
        return PacketType(ptype2f), seq2f, obj
    # Legacy JSON+CRC framing
    if not hasattr(reader, "_replay_window"):
        reader._replay_window = ReplayWindow()
    header_bytes = reader.read(HEADER_LEN)
    if len(header_bytes) < HEADER_LEN:
        raise IncompleteError("Incomplete header")
    magic, version, ptype_byte, seq, length = struct.unpack(
        ">HBBII", header_bytes[:12]
    )
    if magic != MAGIC or version != VERSION:
        raise FrameError("magic/version mismatch")
    crc_expected = struct.unpack(
        ">I", header_bytes[12:16]
    )[0]
    payload = reader.read(length)
    if len(payload) < length:
        raise IncompleteError("Incomplete payload")
    if _crc32(header_bytes[:12] + payload) != crc_expected:
        raise CrcError("CRC mismatch")
    # Replay protection
    if not reader._replay_window.check(seq):
        raise FrameError("Replay protection: drop replayed or too-old sequences")
    reader._replay_window.update(seq)
    obj = json.loads(payload)
    return PacketType(ptype_byte), seq, obj


# ---------------------------------------------------------------------------
# Convenience wrappers for file-like objects
# ---------------------------------------------------------------------------


def send_pkt(w: BufferedWriter, ptype: PacketType, seq: int, obj: Any) -> None:
    """Write a single framed packet to buffered writer *w* and flush."""
    frame = pack(ptype, seq, obj)
    if not hasattr(w, '_retrans_buffer'):
        w._retrans_buffer = RetransmissionBuffer()
    w._retrans_buffer.add(seq, frame)
    w.write(frame)
    w.flush()


def recv_pkt(r: BufferedReader) -> Tuple[PacketType, int, Any]:
    """Blocking helper that returns the next `(ptype, seq, obj)` tuple from *r*."""
    # Initialize replay window on this reader
    if not hasattr(r, "_replay_window"):
        r._replay_window = ReplayWindow()
    # Attach writer if provided (for NAK/ACK responses)
    writer = getattr(r, '_writer', None)
    # AEAD framing when encryption enabled
    if _SECRET_KEY is not None:
        from .encryption import complete_rekey
        from cryptography.exceptions import InvalidTag
        while True:
            # Read AEAD header
            header_len = AEAD_HEADER_STRUCT.size
            header = r.read(header_len)
            if len(header) < header_len:
                raise IncompleteError("Incomplete header")
            magic, version, ptype_val, seq, nonce, length = AEAD_HEADER_STRUCT.unpack(header)
            cipher = r.read(length)
            if len(cipher) < length:
                raise IncompleteError("Incomplete payload")
            frame = header + cipher
            try:
                magic2, version2, ptype2, seq2, plaintext = aead_unpack(frame)
            except InvalidTag:
                # authentication failure: request retransmission
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
            # Replay protection: drop replayed or too-old sequences
            if not r._replay_window.check(seq2):
                continue
            r._replay_window.update(seq2)
            # Send ACK to prune buffer
            if writer is not None:
                send_pkt(writer, PacketType.ACK, seq2, None)
            # Parse payload
            try:
                obj = json.loads(plaintext)
            except Exception:
                obj = plaintext
            return PacketType(ptype2), seq2, obj
    # Legacy JSON+CRC framing
    while True:
        header_bytes = r.read(HEADER_LEN)
        if len(header_bytes) < HEADER_LEN:
            raise IncompleteError("Incomplete header")
        magic, version, ptype_byte, seq, length = struct.unpack(
            ">HBBII", header_bytes[:12]
        )
        if magic != MAGIC or version != VERSION:
            raise FrameError("magic/version mismatch")
        crc_expected = struct.unpack(
            ">I", header_bytes[12:16]
        )[0]
        payload = r.read(length)
        if len(payload) < length:
            raise IncompleteError("Incomplete payload")
        if _crc32(header_bytes[:12] + payload) != crc_expected:
            # CRC failure: request retransmission
            if writer is not None:
                send_pkt(writer, PacketType.NAK, seq, None)
            continue
        # Replay protection: drop replayed or too-old sequences
        if not r._replay_window.check(seq):
            continue
        r._replay_window.update(seq)
        # Send ACK to prune buffer
        if writer is not None:
            send_pkt(writer, PacketType.ACK, seq, None)
        obj = json.loads(payload)
        return PacketType(ptype_byte), seq, obj


# Public helpers ----------------------------------------------------------------

__all__ = [
    "PacketType",
    "enable_encryption",
    "pack",
    "unpack",
    "send_pkt",
    "recv_pkt",
]
