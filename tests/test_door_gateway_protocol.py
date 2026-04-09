from __future__ import annotations

import pytest

from door_gateway.protocol import PACKET_LEN, parse_packet


def test_parse_valid_packet() -> None:
    packet = b"!DOORS:1=\x00;2=\x01;3=\x00;"
    assert len(packet) == PACKET_LEN
    assert parse_packet(packet) == {1: 0, 2: 1, 3: 0}


def test_parse_invalid_prefix() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORX:1=\x00;2=\x01;3=\x00;")


def test_parse_invalid_state_byte() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x02;2=\x01;3=\x00;")
