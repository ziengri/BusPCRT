from __future__ import annotations

from .protocol import HEADER, PACKET_LEN


def extract_packets(buffer: bytearray) -> list[bytes]:
    """
    Extract fixed-size packets from a streaming byte buffer.

    Keeps a possible trailing header prefix in the buffer for the next read.
    """
    packets: list[bytes] = []
    header_len = len(HEADER)

    while True:
        idx = buffer.find(HEADER)
        if idx < 0:
            # Keep only a tail that may be a prefix of HEADER.
            if len(buffer) > header_len - 1:
                del buffer[: len(buffer) - (header_len - 1)]
            break

        if idx > 0:
            del buffer[:idx]

        if len(buffer) < PACKET_LEN:
            break

        packet = bytes(buffer[:PACKET_LEN])
        del buffer[:PACKET_LEN]
        packets.append(packet)

    return packets
