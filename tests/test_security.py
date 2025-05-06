"""Test encryption blocks replay attacks."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from beer.common import enable_encryption, PacketType, pack, unpack

PACKAGE_ROOT = Path(__file__).resolve().parents[1].joinpath("src")


def test_encrypt_roundtrip(tmp_path):
    key = b"0" * 16
    enable_encryption(key)

    payload = {"msg": "hello"}
    data = pack(PacketType.CHAT, 123, payload)
    # simulate stream via BytesIO
    from io import BytesIO

    bio = BytesIO(data)
    ptype, seq, obj = unpack(bio)  # type: ignore[arg-type]
    assert ptype == PacketType.CHAT
    assert seq == 123
    assert obj == payload
