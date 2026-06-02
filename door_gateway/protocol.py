from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

HEADER = b"!DOORS:"


@dataclass(frozen=True)
class DoorTelemetry:
    state: int
    voltage: float


def validate_door_count(door_count: int) -> int:
    if int(door_count) not in (3, 4):
        raise ValueError(f"Unsupported door count: {door_count}")
    return int(door_count)


def configured_door_ids(door_count: int = 3) -> tuple[int, ...]:
    count = validate_door_count(door_count)
    return tuple(range(1, count + 1))


def build_packet(doors: Mapping[int, DoorTelemetry], *, door_count: int = 3) -> bytes:
    packet = bytearray(HEADER)
    for door_id in configured_door_ids(door_count):
        telemetry = doors[door_id]
        state = int(telemetry.state)
        if state not in (0, 1):
            raise ValueError(f"Invalid door state bytes: door={door_id} state={state}")
        packet.extend(f"{door_id}=".encode("ascii"))
        packet.append(state)
        packet.append(ord(","))
        packet.extend(str(float(telemetry.voltage)).encode("ascii"))
        packet.append(ord(";"))
    return bytes(packet)


def parse_packet(packet: bytes, *, door_count: int = 3) -> dict[int, DoorTelemetry]:
    """Parse one packet like b'!DOORS:1=\x00,0.0;2=\x01,12.4;3=\x00,0.1;'."""
    expected_ids = set(configured_door_ids(door_count))
    if packet[: len(HEADER)] != HEADER:
        raise ValueError("Invalid packet prefix")
    if not packet.endswith(b";"):
        raise ValueError("Packet must end with ';'")

    body = packet[len(HEADER) :]
    raw_entries = body.split(b";")
    if raw_entries[-1] != b"":
        raise ValueError("Invalid packet termination")
    entries = raw_entries[:-1]
    if len(entries) != len(expected_ids):
        raise ValueError(f"Invalid door entry count: {len(entries)}")

    parsed: dict[int, DoorTelemetry] = {}
    for entry in entries:
        try:
            door_raw, payload = entry.split(b"=", 1)
        except ValueError as exc:
            raise ValueError(f"Invalid packet entry: {entry!r}") from exc

        try:
            door_id = int(door_raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid door id bytes: {door_raw!r}") from exc

        if door_id not in expected_ids:
            raise ValueError(f"Unexpected door id: {door_id}")
        if door_id in parsed:
            raise ValueError(f"Duplicate door id: {door_id}")
        if len(payload) < 3:
            raise ValueError(f"Invalid packet payload: door={door_id}")

        state = payload[0]
        if state not in (0, 1):
            raise ValueError(f"Invalid door state bytes: door={door_id} state={state}")
        if payload[1] != ord(","):
            raise ValueError(f"Missing voltage separator: door={door_id}")

        voltage_raw = payload[2:]
        if not voltage_raw:
            raise ValueError(f"Missing voltage value: door={door_id}")

        try:
            voltage = float(voltage_raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid voltage value: door={door_id} raw={voltage_raw!r}") from exc

        parsed[door_id] = DoorTelemetry(state=state, voltage=voltage)

    missing_ids = expected_ids.difference(parsed)
    if missing_ids:
        raise ValueError(f"Missing door ids: {sorted(missing_ids)}")
    return parsed
