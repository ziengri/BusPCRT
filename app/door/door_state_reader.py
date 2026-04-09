from __future__ import annotations

from pathlib import Path

from .doors_protocol_parser import DoorsProtocolParser


class DoorPacketFileReader:
    """Reads raw protocol packet from door.sock and parses channels map."""

    def __init__(self, path: str | Path = "door.sock"):
        self.path = Path(path)
        self._parser = DoorsProtocolParser()

    def read_packet(self) -> str | None:
        try:
            text = self.path.read_text(encoding="ascii").strip()
        except OSError:
            return None
        return text or None

    def read_channels(self) -> dict[int, int] | None:
        packet = self.read_packet()
        if packet is None:
            return None
        try:
            return self._parser.parse(packet)
        except ValueError:
            return None


class ChannelDoorStateReader:
    """Door state reader for recorder: True when selected channel is open."""

    def __init__(
        self,
        path: str | Path,
        door_channel: int,
        open_value: int = 1,
    ):
        self._reader = DoorPacketFileReader(path)
        self._door_channel = int(door_channel)
        self._open_value = int(open_value)

    def read(self) -> bool:
        channels = self._reader.read_channels()
        if not channels:
            return False
        return channels.get(self._door_channel, 0) == self._open_value

    def close(self) -> None:
        return None


class AnyDoorOpenStateReader:
    """Door state reader for processor: True when any channel is open."""

    def __init__(
        self,
        path: str | Path,
        open_value: int = 1,
    ):
        self._reader = DoorPacketFileReader(path)
        self._open_value = int(open_value)

    def read(self) -> bool:
        channels = self._reader.read_channels()
        if not channels:
            return False
        return any(value == self._open_value for value in channels.values())

    def close(self) -> None:
        return None
