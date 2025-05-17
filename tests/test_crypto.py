import pytest
import json
from io import BytesIO

from beer.common import pack, unpack, enable_encryption, PacketType, CrcError, DEFAULT_KEY


def test_crc32_roundtrip():
    obj = {"hello": "world", "num": 42}
    seq = 7
    ptype = PacketType.GAME
    pkt = pack(ptype, seq, obj)
    buf = BytesIO(pkt)
    ptype2, seq2, obj2 = unpack(buf)
    assert ptype2 == ptype
    assert seq2 == seq
    assert obj2 == obj


def test_crc32_corruption():
    obj = {"a": 1}
    pkt = pack(PacketType.GAME, 1, obj)
    # Corrupt one byte in payload
    corrupted = bytearray(pkt)
    corrupted[-1] ^= 0xFF
    buf = BytesIO(corrupted)
    with pytest.raises(CrcError):
        unpack(buf)


def test_aes_ctr_encryption_roundtrip():
    key = DEFAULT_KEY  # 16-byte default
    enable_encryption(key)
    obj = {"secret": "data", "value": [1, 2, 3]}
    seq = 123
    ptype = PacketType.CHAT
    pkt = pack(ptype, seq, obj)
    buf = BytesIO(pkt)
    ptype2, seq2, obj2 = unpack(buf)
    assert ptype2 == ptype
    assert seq2 == seq
    assert obj2 == obj
