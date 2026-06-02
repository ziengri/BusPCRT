from __future__ import annotations

from door_gateway.protocol import DoorTelemetry, build_packet
from door_gateway.serial_reader import extract_packets


def test_extract_packets_partial_chunks() -> None:
    packet = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0.0),
            2: DoorTelemetry(state=1, voltage=12.4),
            3: DoorTelemetry(state=0, voltage=0.1),
        }
    )
    buffer = bytearray(packet[:10])
    assert extract_packets(buffer) == []

    buffer.extend(packet[10:20])
    assert extract_packets(buffer) == []

    buffer.extend(packet[20:])
    packets = extract_packets(buffer)
    assert packets == [packet]
    assert buffer == bytearray()


def test_extract_packets_with_garbage_prefix() -> None:
    packet = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0.0),
            2: DoorTelemetry(state=0, voltage=0.0),
            3: DoorTelemetry(state=0, voltage=0.0),
        }
    )
    buffer = bytearray(b"\xAA\xBBgarbage" + packet)
    packets = extract_packets(buffer)
    assert packets == [packet]


def test_extract_packets_multiple_and_tail() -> None:
    p1 = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0.0),
            2: DoorTelemetry(state=0, voltage=0.0),
            3: DoorTelemetry(state=0, voltage=0.0),
        }
    )
    p2 = build_packet(
        {
            1: DoorTelemetry(state=1, voltage=12.2),
            2: DoorTelemetry(state=1, voltage=12.3),
            3: DoorTelemetry(state=0, voltage=0.1),
        }
    )
    buffer = bytearray(p1 + p2 + b"!DO")
    packets = extract_packets(buffer)
    assert packets == [p1, p2]
    assert buffer == bytearray(b"!DO")


def test_extract_packets_for_four_doors() -> None:
    packet = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0.0),
            2: DoorTelemetry(state=1, voltage=12.4),
            3: DoorTelemetry(state=0, voltage=0.1),
            4: DoorTelemetry(state=1, voltage=11.9),
        },
        door_count=4,
    )
    buffer = bytearray(packet + b"!DO")

    packets = extract_packets(buffer, door_count=4)

    assert packets == [packet]
    assert buffer == bytearray(b"!DO")


def test_extract_packets_waits_for_full_semicolon_count() -> None:
    packet = b"!DOORS:1=\x00,0.0;2=\x01,12.4;"
    buffer = bytearray(packet)

    packets = extract_packets(buffer, door_count=3)

    assert packets == []
    assert buffer == bytearray(packet)


def test_extract_packets_resyncs_to_next_header_after_truncated_packet() -> None:
    valid = build_packet(
        {
            1: DoorTelemetry(state=0, voltage=0.0),
            2: DoorTelemetry(state=1, voltage=12.4),
            3: DoorTelemetry(state=0, voltage=0.1),
        }
    )
    truncated = b"!DOORS:1=\x00,0.0;2=\x01,12.4"
    buffer = bytearray(truncated + valid)

    packets = extract_packets(buffer, door_count=3)

    assert packets == [valid]
    assert buffer == bytearray()
