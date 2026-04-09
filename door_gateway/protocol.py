from __future__ import annotations

HEADER = b"!DOORS:"
PACKET_LEN = 19


def parse_packet(packet: bytes) -> dict[int, int]:
    """Parse one 19-byte binary packet: b'!DOORS:1=\\x00;2=\\x01;3=\\x00;'."""
    if len(packet) != PACKET_LEN:
        raise ValueError(f"Invalid packet length: {len(packet)}")
    if packet[:7] != HEADER:
        raise ValueError("Invalid packet prefix")

    expected_layout = {
        7: ord("1"),
        8: ord("="),
        10: ord(";"),
        11: ord("2"),
        12: ord("="),
        14: ord(";"),
        15: ord("3"),
        16: ord("="),
        18: ord(";"),
    }
    for idx, byte_value in expected_layout.items():
        if packet[idx] != byte_value:
            raise ValueError(f"Invalid packet structure at index {idx}")

    s1 = packet[9]
    s2 = packet[13]
    s3 = packet[17]
    if s1 not in (0, 1) or s2 not in (0, 1) or s3 not in (0, 1):
        raise ValueError(f"Invalid door state bytes: {[s1, s2, s3]}")

    return {1: s1, 2: s2, 3: s3}
