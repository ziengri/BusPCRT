from __future__ import annotations

from .protocol import HEADER, packet_length, packet_min_length


def extract_packets(buffer: bytearray, *, door_count: int = 3) -> list[bytes]:
    """
    Extract fixed-size packets from a streaming byte buffer.

    Keeps a possible trailing header prefix in the buffer for the next read.
    """
    packets: list[bytes] = []
    header_len = len(HEADER)
    expected_len = packet_length(door_count)
    min_len = packet_min_length(door_count)

    while True:
        idx = buffer.find(HEADER)
        if idx < 0:
            # Keep only a tail that may be a prefix of HEADER.
            if len(buffer) > header_len - 1:
                del buffer[: len(buffer) - (header_len - 1)]
            break

        if idx > 0:
            del buffer[:idx]

        if len(buffer) < min_len:
            break

        packet_len = expected_len if len(buffer) >= expected_len and buffer[expected_len - 1] == ord(";") else min_len
        packet = bytes(buffer[:packet_len])
        del buffer[:packet_len]
        packets.append(packet)

    return packets
