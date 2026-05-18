from __future__ import annotations

import pytest

from door_gateway.protocol import PACKET_LEN, build_packet, packet_length, packet_min_length, parse_packet


def test_parse_valid_packet() -> None:
    packet = build_packet({1: 0, 2: 1, 3: 0})
    assert len(packet) == PACKET_LEN
    assert parse_packet(packet) == {1: 0, 2: 1, 3: 0}


def test_parse_valid_packet_for_four_doors() -> None:
    packet = build_packet({1: 0, 2: 1, 3: 0, 4: 1}, door_count=4)

    assert len(packet) == packet_length(4)
    assert parse_packet(packet, door_count=4) == {1: 0, 2: 1, 3: 0, 4: 1}


def test_parse_valid_packet_without_final_semicolon() -> None:
    packet = b"!DOORS:1=\x00;2=\x01;3=\x00"

    assert len(packet) == packet_min_length(3)
    assert parse_packet(packet) == {1: 0, 2: 1, 3: 0}


def test_parse_valid_four_door_packet_without_final_semicolon() -> None:
    packet = b"!DOORS:1=\x00;2=\x01;3=\x00;4=\x01"

    assert len(packet) == packet_min_length(4)
    assert parse_packet(packet, door_count=4) == {1: 0, 2: 1, 3: 0, 4: 1}


def test_parse_invalid_prefix() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORX:1=\x00;2=\x01;3=\x00;")


def test_parse_invalid_state_byte() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x02;2=\x01;3=\x00;")
