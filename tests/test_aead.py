import pytest
import os
import random
import io
from cryptography.exceptions import InvalidTag

import beer.common as common
from beer.encryption import pack as aead_pack, unpack as aead_unpack, enable_encryption as aead_enable, HEADER_STRUCT
from beer.common import pack, unpack, send_pkt, recv_pkt, PacketType, FrameError, IncompleteError
from beer.replay import ReplayWindow

# Round-trip AEAD payload tests
def test_roundtrip_payloads():
    for size in [0, 16, 1024, 1024*1024 + 1]:
        payload = os.urandom(size)
        frame = aead_pack(PacketType.GAME.value, 42, payload)
        # Direct unpack
        magic, version, ptype, seq, plaintext = aead_unpack(frame)
        assert magic == HEADER_STRUCT.unpack(frame[:HEADER_STRUCT.size])[0]
        assert version == HEADER_STRUCT.unpack(frame[:HEADER_STRUCT.size])[1]
        assert ptype == PacketType.GAME.value
        assert seq == 42
        assert plaintext == payload
        # common unpack
        pkt, ptype_enum, seq_out = unpack(frame)
        # payload is under 'obj' key in common.pack/unpack
        # but unpack(frame) from common returns pkt dict
        # Here we simulate pack via common.pack
        common_frame = pack({'ptype': PacketType.GAME.value, 'seq': 99, 'obj': payload})
        pkt2, p2, s2 = common.unpack(common_frame)
        assert p2 == PacketType.GAME
        assert s2 == 99
        assert pkt2.get('obj') == payload

# Wrong-key decryption should fail and recover
def test_wrong_key_fails():
    payload = b"secret data"
    frame = aead_pack(PacketType.GAME.value, 99, payload)
    wrong_key = bytes([b ^ 0xFF for b in bytes(range(16))])
    aead_enable(wrong_key)
    with pytest.raises(InvalidTag):
        aead_unpack(frame)
    # restore correct key
    key = bytes(range(16))
    aead_enable(key)
    magic, version, ptype, seq, plaintext = aead_unpack(frame)
    assert plaintext == payload

# Tampering tests
@ pytest.mark.parametrize("idx_func", [
    lambda length: random.randint(HEADER_STRUCT.size, length-1),      # ciphertext
    lambda length: length-1,                                         # auth tag
])
def test_tampering_cipher_or_tag(idx_func):
    payload = b"hello tamper"
    frame = aead_pack(PacketType.CHAT.value, 7, payload)
    corrupt = bytearray(frame)
    idx = idx_func(len(corrupt))
    corrupt[idx] ^= 0xFF
    with pytest.raises(InvalidTag):
        aead_unpack(bytes(corrupt))

# Header tampering should raise FrameError via common.unpack
def test_header_tampering_raises_frame_error():
    payload = b"header"
    frame = aead_pack(PacketType.CHAT.value, 3, payload)
    corrupt = bytearray(frame)
    corrupt[0] ^= 0xFF  # corrupt magic
    with pytest.raises(FrameError):
        unpack(bytes(corrupt))

# Replay protection tests
def test_replay_protection_duplicate():
    buf = io.BytesIO()
    common.send_pkt(buf, PacketType.GAME, 5, {"msg": 123})
    buf.seek(0)
    # first recv
    p1, s1, o1 = common.recv_pkt(buf)
    assert s1 == 5
    # second recv: duplicate seq -> dropped, then EOF -> IncompleteError
    buf.seek(0)
    with pytest.raises(IncompleteError):
        common.recv_pkt(buf)

# Out-of-order handling within window
def test_out_of_order_within_window():
    buf = io.BytesIO()
    # write frames with seq 1,3,2,4
    common.send_pkt(buf, PacketType.GAME, 1, {"a":1})
    common.send_pkt(buf, PacketType.GAME, 3, {"b":3})
    common.send_pkt(buf, PacketType.GAME, 2, {"c":2})
    common.send_pkt(buf, PacketType.GAME, 4, {"d":4})
    buf.seek(0)
    seqs = []
    for _ in range(4):
        p, seq, obj = common.recv_pkt(buf)
        seqs.append(seq)
    assert seqs == [1, 3, 2, 4]

# Nonce uniqueness and randomness
def test_nonce_uniqueness_and_ciphertext_variation():
    payload = b"repeat-test"
    frames = [aead_pack(PacketType.CHAT.value, 10, payload) for _ in range(100)]
    nonces = {bytes(frame[4:4+12]) for frame in frames}
    assert len(nonces) == 100
    # ciphertext variation
    ciphers = {frame for frame in frames}
    assert len(ciphers) == 100

# Edge-case oversized payload should raise or error
def test_oversized_payload_rejected_or_error():
    # assume arbitrary max size e.g. 10MB
    huge = os.urandom(20 * 1024 * 1024)
    with pytest.raises(Exception):
        aead_pack(PacketType.GAME.value, 0, huge)
