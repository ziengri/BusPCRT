from __future__ import annotations

from collections.abc import Mapping

HEADER = b"!DOORS:"
PACKET_LEN = 19


def validate_door_count(door_count: int) -> int:
    if int(door_count) not in (3, 4):
        raise ValueError(f"Unsupported door count: {door_count}")
    return int(door_count)


def configured_door_ids(door_count: int = 3) -> tuple[int, ...]:
    count = validate_door_count(door_count)
    return tuple(range(1, count + 1))


def packet_length(door_count: int = 3) -> int:
    return len(HEADER) + (4 * validate_door_count(door_count))


def packet_min_length(door_count: int = 3) -> int:
    return packet_length(door_count) - 1


def build_packet(doors: Mapping[int, int], *, door_count: int = 3) -> bytes:
    packet = bytearray(HEADER)
    for door_id in configured_door_ids(door_count):
        state = int(doors[door_id])
        if state not in (0, 1):
            raise ValueError(f"Invalid door state bytes: door={door_id} state={state}")
        packet.extend(f"{door_id}=".encode("ascii"))
        packet.append(state)
        packet.append(ord(";"))
    return bytes(packet)


def parse_packet(packet: bytes, *, door_count: int = 3) -> dict[int, int]:
    """Parse one binary packet like b'!DOORS:1=\\x00;2=\\x01;3=\\x00;'."""
    expected_len = packet_length(door_count)
    min_len = packet_min_length(door_count)
    if len(packet) not in (min_len, expected_len):
        raise ValueError(f"Invalid packet length: {len(packet)}")
    if packet[:7] != HEADER:
        raise ValueError("Invalid packet prefix")

    cursor = len(HEADER)
    parsed: dict[int, int] = {}
    for door_id in configured_door_ids(door_count):
        label = f"{door_id}=".encode("ascii")
        if packet[cursor : cursor + len(label)] != label:
            raise ValueError(f"Invalid packet structure at index {cursor}")
        cursor += len(label)
        state = packet[cursor]
        if state not in (0, 1):
            raise ValueError(f"Invalid door state bytes: door={door_id} state={state}")
        cursor += 1
        is_last_door = door_id == door_count
        if is_last_door and cursor == len(packet):
            parsed[door_id] = state
            continue
        if cursor >= len(packet) or packet[cursor] != ord(";"):
            raise ValueError(f"Invalid packet structure at index {cursor}")
        cursor += 1
        parsed[door_id] = state

    return parsed
