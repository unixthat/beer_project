import pytest
from io import BytesIO

import beer.common as common
from beer.common import (
    pack,
    unpack,
    PacketType,
    FrameError,
    CrcError,
    IncompleteError,
    HEADER_LEN,
    send_pkt,
    recv_pkt,
)


def test_pack_unpack_roundtrip():
    obj = {"foo": "bar", "nested": [1, 2, {"x": True}]}
    seq = 12345
    data = pack(PacketType.GAME, seq, obj)
    buf = BytesIO(data)
    ptype, seq_out, obj_out = unpack(buf)
    assert ptype == PacketType.GAME
    assert seq_out == seq
    assert obj_out == obj


def test_header_and_crc_fields():
    obj = {"hello": "world"}
    seq = 1
    data = pack(PacketType.CHAT, seq, obj)
    # parse header fields
    import struct, zlib

    magic, version, ptype_byte, seq_u32, length = struct.unpack(">HBBII", data[:12])
    assert magic == common.MAGIC
    assert version == common.VERSION
    assert ptype_byte == PacketType.CHAT.value
    assert seq_u32 == seq
    payload = data[16:]
    assert length == len(payload)
    # verify CRC
    crc_expected = struct.unpack(">I", data[12:16])[0]
    crc_actual = zlib.crc32(data[:12] + payload) & 0xFFFFFFFF
    assert crc_actual == crc_expected


def test_magic_mismatch_raises_FrameError():
    data = pack(PacketType.GAME, 0, {"x": 1})
    bad = b"\x00\x00" + data[2:]
    with pytest.raises(FrameError):
        unpack(BytesIO(bad))


def test_version_mismatch_raises_FrameError():
    data = pack(PacketType.GAME, 0, {"x": 1})
    bad = data[:2] + b"\x02" + data[3:]
    with pytest.raises(FrameError):
        unpack(BytesIO(bad))


def test_incomplete_header_raises_IncompleteError():
    data = pack(PacketType.GAME, 0, {"x": 1})
    with pytest.raises(IncompleteError):
        unpack(BytesIO(data[: HEADER_LEN - 1]))


def test_incomplete_payload_raises_IncompleteError():
    data = pack(PacketType.GAME, 0, {"x": 1})
    cut = 16 + (len(data) - 16) // 2
    with pytest.raises(IncompleteError):
        unpack(BytesIO(data[:cut]))


def test_crc_mismatch_raises_CrcError():
    data = pack(PacketType.GAME, 5, {"foo": "bar"})
    corrupt = bytearray(data)
    corrupt[16] ^= 0xFF
    with pytest.raises(CrcError):
        unpack(BytesIO(corrupt))


def test_send_pkt_and_recv_pkt_roundtrip():
    buf = BytesIO()
    send_pkt(buf, PacketType.CHAT, 99, {"text": "ping"})
    buf.seek(0)
    ptype, seq, obj = recv_pkt(buf)
    assert ptype == PacketType.CHAT
    assert seq == 99
    assert obj == {"text": "ping"}


@pytest.mark.skipif(common.Cipher is None, reason="cryptography not installed")
def test_encryption_roundtrip():
    # Backup and enable a fixed key
    orig_key = common._SECRET_KEY
    key = bytes(range(16))
    common.enable_encryption(key)
    try:
        buf = BytesIO()
        obj = {"secret": "data"}
        buf.write(pack(PacketType.GAME, 42, obj))
        buf.seek(0)
        ptype, seq, obj_out = unpack(buf)
        assert ptype == PacketType.GAME
        assert seq == 42
        assert obj_out == obj
    finally:
        common._SECRET_KEY = orig_key


def test_multiple_frames_stream():
    buf = BytesIO()
    send_pkt(buf, PacketType.GAME, 1, {"msg": 1})
    send_pkt(buf, PacketType.CHAT, 2, {"msg": 2})
    buf.seek(0)
    p1, s1, o1 = recv_pkt(buf)
    p2, s2, o2 = recv_pkt(buf)
    assert p1 == PacketType.GAME and s1 == 1 and o1 == {"msg": 1}
    assert p2 == PacketType.CHAT and s2 == 2 and o2 == {"msg": 2}
