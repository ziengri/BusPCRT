from __future__ import annotations

from .protocol import HEADER, packet_length


def extract_packets(buffer: bytearray, *, door_count: int = 3) -> list[bytes]:
    """
    Extract fixed-size packets from a streaming byte buffer.

    Keeps a possible trailing header prefix in the buffer for the next read.
    """
    packets: list[bytes] = []
    header_len = len(HEADER)
    expected_len = packet_length(door_count)

    while True:
        idx = buffer.find(HEADER)
        if idx < 0:
            # Keep only a tail that may be a prefix of HEADER.
            if len(buffer) > header_len - 1:
                del buffer[: len(buffer) - (header_len - 1)]
            break

        if idx > 0:
            del buffer[:idx]

        if len(buffer) < expected_len:
            break

        packet = bytes(buffer[:expected_len])
        del buffer[:expected_len]
        packets.append(packet)

    return packets
