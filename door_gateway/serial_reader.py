from __future__ import annotations

from .protocol import HEADER, packet_min_size_bytes, packet_size_bytes, validate_door_count


def _find_packet_end(buffer: bytearray, *, door_count: int) -> int | None:
    min_size = packet_min_size_bytes(door_count)
    max_size = packet_size_bytes(door_count)
    if len(buffer) < min_size:
        return None
    if len(buffer) >= max_size and buffer[max_size - 1] == ord(";"):
        return max_size
    return min_size


def extract_packets(buffer: bytearray, *, door_count: int = 3) -> list[bytes]:
    """
    Extract variable-size door packets from a streaming byte buffer.

    Keeps a possible trailing header prefix in the buffer for the next read.
    """
    validate_door_count(door_count)
    packets: list[bytes] = []
    header_len = len(HEADER)

    while True:
        idx = buffer.find(HEADER)
        if idx < 0:
            if len(buffer) > header_len - 1:
                del buffer[: len(buffer) - (header_len - 1)]
            break

        if idx > 0:
            del buffer[:idx]

        next_header_idx = buffer.find(HEADER, header_len)
        packet_end = _find_packet_end(buffer, door_count=door_count)
        if next_header_idx >= 0 and (packet_end is None or next_header_idx < packet_end):
            del buffer[:next_header_idx]
            continue
        if packet_end is None:
            break

        packet = bytes(buffer[:packet_end])
        del buffer[:packet_end]
        packets.append(packet)

    return packets
