from __future__ import annotations

from .protocol import HEADER, packet_size_bytes, validate_door_count


def extract_packets(buffer: bytearray, *, door_count: int = 3) -> list[bytes]:
    """
    Extract variable-size door packets from a streaming byte buffer.

    Keeps a possible trailing header prefix in the buffer for the next read.
    """
    validate_door_count(door_count)
    packets: list[bytes] = []
    header_len = len(HEADER)
    packet_len = packet_size_bytes(door_count)

    while True:
        idx = buffer.find(HEADER)
        if idx < 0:
            if len(buffer) > header_len - 1:
                del buffer[: len(buffer) - (header_len - 1)]
            break

        if idx > 0:
            del buffer[:idx]

        next_header_idx = buffer.find(HEADER, 1)
        if 0 < next_header_idx < packet_len:
            del buffer[:next_header_idx]
            continue
        if len(buffer) < packet_len:
            break

        packet = bytes(buffer[:packet_len])
        del buffer[:packet_len]
        packets.append(packet)

    return packets
