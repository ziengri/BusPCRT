from __future__ import annotations

import pytest

from door_gateway.protocol import DoorTelemetry, build_packet, packet_size_bytes, parse_packet


def test_parse_valid_packet() -> None:
    packet = build_packet(
        {
            1: DoorTelemetry(state=1, voltage=0x0280),
            2: DoorTelemetry(state=1, voltage=0x03AF),
            3: DoorTelemetry(state=0, voltage=0x0193),
        }
    )

    assert len(packet) == packet_size_bytes(3) == 28
    assert parse_packet(packet) == {
        1: DoorTelemetry(state=1, voltage=0x0280),
        2: DoorTelemetry(state=1, voltage=0x03AF),
        3: DoorTelemetry(state=0, voltage=0x0193),
    }


def test_parse_valid_packet_with_single_byte_voltage() -> None:
    packet = b"!DOORS:1=\x01,\x80;2=\x00,\x09;3=\x01,\xFF;"

    assert parse_packet(packet) == {
        1: DoorTelemetry(state=1, voltage=0x80),
        2: DoorTelemetry(state=0, voltage=0x09),
        3: DoorTelemetry(state=1, voltage=0xFF),
    }


def test_parse_valid_packet_with_mixed_voltage_width() -> None:
    packet = b"!DOORS:1=\x01,\x80;2=\x01,\x03\xAF;3=\x00,\x09;"

    assert parse_packet(packet) == {
        1: DoorTelemetry(state=1, voltage=0x80),
        2: DoorTelemetry(state=1, voltage=0x03AF),
        3: DoorTelemetry(state=0, voltage=0x09),
    }


def test_parse_valid_packet_for_four_doors() -> None:
    packet = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0x0010),
            2: DoorTelemetry(state=1, voltage=0x12F0),
            3: DoorTelemetry(state=0, voltage=0x0001),
            4: DoorTelemetry(state=1, voltage=0x0A7E),
        },
        door_count=4,
    )

    assert len(packet) == packet_size_bytes(4) == 35
    assert parse_packet(packet, door_count=4) == {
        1: DoorTelemetry(state=0, voltage=0x0010),
        2: DoorTelemetry(state=1, voltage=0x12F0),
        3: DoorTelemetry(state=0, voltage=0x0001),
        4: DoorTelemetry(state=1, voltage=0x0A7E),
    }


def test_parse_invalid_prefix() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORX:1=\x00,\x00\x00;2=\x01,\x00\x09;3=\x00,\x00\x01;")


def test_parse_invalid_state_byte() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x02,\x00\x00;2=\x01,\x00\x09;3=\x00,\x00\x01;")


def test_parse_invalid_voltage() -> None:
    packet = b"!DOORS:1=\x00,\x00\x00;2=\x01,\xFF\xFE;3=\x00,\x7F\x01;"
    parsed = parse_packet(packet)
    assert parsed[2].voltage == 65534


def test_parse_missing_voltage() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,\x00\x00;2=\x01,;3=\x00,\x00\x01;")


def test_parse_rejects_payload_longer_than_two_voltage_bytes() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,\x00\x00\x00;2=\x01,\x09;3=\x00,\x01;")


def test_parse_missing_door() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,\x00\x00;2=\x01,\x00\x09;", door_count=3)


def test_parse_duplicate_door() -> None:
    with pytest.raises(ValueError):
        parse_packet(b"!DOORS:1=\x00,\x00\x00;2=\x01,\x00\x09;2=\x00,\x00\x01;")


def test_parse_known_frame_from_device_example() -> None:
    packet = bytes.fromhex("21 44 4F 4F 52 53 3A 31 3D 01 2C 80 3B 32 3D 01 2C AF 3B 33 3D 00 2C 93 3B")
    assert parse_packet(packet) == {
        1: DoorTelemetry(state=1, voltage=0x80),
        2: DoorTelemetry(state=1, voltage=0xAF),
        3: DoorTelemetry(state=0, voltage=0x93),
    }
