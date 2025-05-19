import random
import pytest
from io import BytesIO

from beer.common import pack, unpack, CrcError, PacketType, HEADER_LEN


def flip_random_bit(data: bytes) -> bytes:
    """
    Flip a random bit in the given byte sequence to simulate corruption.
    """
    # Only flip bits in the payload region (skip header and CRC)
    header_len = HEADER_LEN
    if len(data) <= header_len:
        return data
    idx = header_len + random.randrange(len(data) - header_len)
    # choose a random bit to flip
    bit = 1 << random.randrange(8)
    return data[:idx] + bytes([data[idx] ^ bit]) + data[idx+1:]


def test_crc_error_detected():
    """
    Ensure that corrupting a packed frame raises CrcError with correct sequence.
    """
    # Prepare a valid packet
    obj = {'msg': 'test message'}
    seq = 42
    # Pack into framed bytes
    data = pack(PacketType.GAME, seq, obj)
    # Corrupt one random bit
    corrupted = flip_random_bit(data)
    # Feed into unpack and expect CrcError
    stream = BytesIO(corrupted)
    with pytest.raises(CrcError) as exc:
        unpack(stream)
    # The exception should carry the original sequence number
    assert exc.value.seq == seq


def test_valid_frame_survives():
    """
    Ensure that valid frames unpack correctly without error.
    """
    obj = {'msg': 'hello world'}
    seq = 7
    data = pack(PacketType.GAME, seq, obj)
    stream = BytesIO(data)
    ptype, s2, obj2 = unpack(stream)
    assert ptype == PacketType.GAME
    assert s2 == seq
    assert obj2 == obj
