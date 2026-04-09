from __future__ import annotations

from door_gateway.serial_reader import extract_packets


def test_extract_packets_partial_chunks() -> None:
    buffer = bytearray()
    buffer.extend(bytes.fromhex("21 44 4F 4F"))
    assert extract_packets(buffer) == []

    buffer.extend(bytes.fromhex("52 53 3A 31 3D 00"))
    assert extract_packets(buffer) == []

    buffer.extend(bytes.fromhex("3B 32 3D 01 3B 33 3D 00 3B"))
    packets = extract_packets(buffer)
    assert len(packets) == 1
    assert packets[0] == b"!DOORS:1=\x00;2=\x01;3=\x00;"
    assert buffer == bytearray()


def test_extract_packets_with_garbage_prefix() -> None:
    buffer = bytearray(b"\xAA\xBBgarbage!DOORS:1=\x00;2=\x00;3=\x00;")
    packets = extract_packets(buffer)
    assert len(packets) == 1
    assert packets[0] == b"!DOORS:1=\x00;2=\x00;3=\x00;"


def test_extract_packets_multiple_and_tail() -> None:
    p1 = b"!DOORS:1=\x00;2=\x00;3=\x00;"
    p2 = b"!DOORS:1=\x01;2=\x01;3=\x00;"
    buffer = bytearray(p1 + p2 + b"!DO")
    packets = extract_packets(buffer)
    assert packets == [p1, p2]
    assert buffer == bytearray(b"!DO")
