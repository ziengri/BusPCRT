from __future__ import annotations

import pytest

from door_gateway.protocol import DoorTelemetry, build_packet, packet_size_bytes, parse_packet


def test_parse_valid_packet() -> None:
    packet = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0),
            2: DoorTelemetry(state=1, voltage=9),
            3: DoorTelemetry(state=0, voltage=1),
        }
    )

    assert len(packet) == packet_size_bytes(3) == 25
    assert parse_packet(packet) == {
        1: DoorTelemetry(state=0, voltage=0),
        2: DoorTelemetry(state=1, voltage=9),
        3: DoorTelemetry(state=0, voltage=1),
    }


def test_parse_valid_packet_for_four_doors() -> None:
    packet = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0),
            2: DoorTelemetry(state=1, voltage=9),
            3: DoorTelemetry(state=0, voltage=1),
            4: DoorTelemetry(state=1, voltage=8),
        },
        door_count=4,
    )

    assert len(packet) == packet_size_bytes(4) == 31
    assert parse_packet(packet, door_count=4) == {
        1: DoorTelemetry(state=0, voltage=0),
        2: DoorTelemetry(state=1, voltage=9),
        3: DoorTelemetry(state=0, voltage=1),
        4: DoorTelemetry(state=1, voltage=8),
    }


def test_parse_invalid_prefix() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORX:1=\x00,0;2=\x01,9;3=\x00,1;")


def test_parse_invalid_state_byte() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x02,0;2=\x01,9;3=\x00,1;")


def test_parse_invalid_voltage() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,0;2=\x01,a;3=\x00,1;")


def test_parse_missing_voltage() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,0;2=\x01,;3=\x00,1;")


def test_parse_missing_door() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,0;2=\x01,9;", door_count=3)


def test_parse_duplicate_door() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,0;2=\x01,9;2=\x00,1;")
