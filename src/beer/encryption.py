# encryption abstraction module

import os
import struct
import json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
import time
from .keyexchange import generate_key_pair  # for rekeying
from .keyexchange import derive_session_key

# AEAD header format: magic (2 bytes), version (1 byte), packet type (1 byte), sequence (4 bytes), nonce (12 bytes), length (4 bytes)
HEADER_STRUCT = struct.Struct(">HBBI12sI")

# Rekey settings
REKEY_PACKET_THRESHOLD = 1024  # number of packets before auto-rekey
REKEY_TIME_THRESHOLD = 3600.0  # seconds before auto-rekey
_pkt_count = 0
_last_rekey_time = time.time()

_MAGIC = 0xBEEF
_VERSION = 1

_secret_key: bytes | None = None

# Private key placeholder for rekey handshake
_rekey_priv_key = None
# Public rekey ephemeral bytes to send when appropriate
_rekey_pub: bytes | None = None


def enable_encryption(key: bytes) -> None:
    """Set the symmetric encryption key for AEAD operations"""
    global _secret_key
    _secret_key = key
    # Sync key state with common framing module
    try:
        import importlib

        common_mod = importlib.import_module(__package__ + ".common")
        common_mod.enable_encryption(key)
    except Exception:
        # If common module is unavailable, skip syncing
        pass


def complete_rekey(peer_public_bytes: bytes) -> None:
    """Complete a rekey handshake: derive new session key and enable encryption."""
    global _secret_key, _pkt_count, _last_rekey_time, _rekey_priv_key
    if _rekey_priv_key is None:
        raise RuntimeError("No rekey in progress: missing private key")
    # Derive new AES key via HKDF from ECDH secret
    new_key = derive_session_key(_rekey_priv_key, peer_public_bytes)
    # Enable the fresh key
    enable_encryption(new_key)
    # Reset rekey counters
    _pkt_count = 0
    _last_rekey_time = time.time()
    # Clear staged private key
    _rekey_priv_key = None
    # Clear our pending public bytes
    global _rekey_pub
    _rekey_pub = None


def maybe_rekey() -> bytes | None:
    """Check thresholds and generate a fresh ECDH key pair for rekey if needed."""
    global _pkt_count, _last_rekey_time, _rekey_priv_key
    now = time.time()
    if _pkt_count >= REKEY_PACKET_THRESHOLD or (now - _last_rekey_time) >= REKEY_TIME_THRESHOLD:
        # Generate new ephemeral key pair
        pub, priv = generate_key_pair()
        _rekey_priv_key = priv
        # Store public bytes so caller can send a REKEY packet
        global _rekey_pub
        _rekey_pub = pub
        # Reset packet counter and timer
        _pkt_count = 0
        _last_rekey_time = now
        return pub
    return None


def pack(ptype: int, seq: int, payload: bytes) -> bytes:
    """AEAD pack: header + ciphertext+tag"""
    if _secret_key is None:
        raise ValueError("Encryption key not set")
    # Reject excessively large payloads (e.g., >10 MiB)
    MAX_PAYLOAD = 10 * 1024 * 1024
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"Payload too large: {len(payload)} bytes")
    nonce = os.urandom(12)
    aesgcm = AESGCM(_secret_key)
    ciphertext = aesgcm.encrypt(nonce, payload, None)
    length = len(ciphertext)
    header = HEADER_STRUCT.pack(_MAGIC, _VERSION, ptype, seq, nonce, length)
    # Increment packet counter and check for auto-rekey condition
    global _pkt_count
    _pkt_count += 1
    pub = maybe_rekey()
    # TODO: if pub is not None, caller should send a REKEY packet containing this public key
    return header + ciphertext


def unpack(frame: bytes) -> tuple[int, int, int, int, bytes]:
    """AEAD unpack: returns (magic, version, ptype, seq, plaintext)"""
    if _secret_key is None:
        raise ValueError("Encryption key not set")
    header_size = HEADER_STRUCT.size
    hdr = frame[:header_size]
    magic, version, ptype, seq, nonce, length = HEADER_STRUCT.unpack(hdr)
    ciphertext = frame[header_size : header_size + length]
    aesgcm = AESGCM(_secret_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return magic, version, ptype, seq, plaintext


def get_rekey_pub() -> bytes | None:
    """Return pending rekey public bytes (or None if none)."""
    return _rekey_pub
