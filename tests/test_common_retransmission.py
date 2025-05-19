import io
import pytest
from io import BufferedWriter
from beer.common import send_pkt, handle_control_frame, PacketType, _send_buffers


def test_send_buffer_prune_and_retransmit():
    # Prepare an in-memory writer
    buf_io = io.BytesIO()
    writer = BufferedWriter(buf_io)
    # Ensure fresh buffer
    _send_buffers.clear()

    # Send two frames
    send_pkt(writer, PacketType.GAME, 1, {"msg": "hello"})
    send_pkt(writer, PacketType.GAME, 2, {"msg": "world"})
    writer.flush()

    # Buffer should hold both sequences
    buf = _send_buffers.get(writer)
    assert buf is not None
    assert 1 in buf and 2 in buf

    # ACK sequence 1 -> should prune seq 1
    handle_control_frame(writer, PacketType.ACK, 1)
    assert 1 not in buf and 2 in buf

    # ACK sequence 2 -> buffer empty
    handle_control_frame(writer, PacketType.ACK, 2)
    assert 2 not in buf

    # Send a third frame
    send_pkt(writer, PacketType.GAME, 3, {"msg": "again"})
    writer.flush()
    buf = _send_buffers.get(writer)
    assert buf and 3 in buf

    # Record length before NAK
    before = len(buf_io.getvalue())
    # NAK sequence 3 -> retransmit, so buffer_io grows
    handle_control_frame(writer, PacketType.NAK, 3)
    after = len(buf_io.getvalue())
    assert after > before


def test_nak_without_seq():
    # NAK for unknown seq should be no-op
    buf_io = io.BytesIO()
    writer = BufferedWriter(buf_io)
    _send_buffers.clear()
    # NAK seq 99 when buffer empty
    handle_control_frame(writer, PacketType.NAK, 99)
    # Nothing written
    assert buf_io.getvalue() == b''
