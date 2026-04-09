from __future__ import annotations

from pathlib import Path

from app.door.door_state_reader import AnyDoorOpenStateReader, ChannelDoorStateReader, DoorPacketFileReader


def test_file_reader_packet_and_channels(tmp_path: Path) -> None:
    door_file = tmp_path / "door.sock"
    door_file.write_text("!DOORS;1=1;2=0;3=0;", encoding="ascii")

    reader = DoorPacketFileReader(door_file)
    assert reader.read_packet() == "!DOORS;1=1;2=0;3=0;"
    assert reader.read_channels() == {1: 1, 2: 0, 3: 0}


def test_channel_reader_fail_safe_closed(tmp_path: Path) -> None:
    reader = ChannelDoorStateReader(tmp_path / "missing.sock", door_channel=1, open_value=1)
    assert reader.read() is False


def test_any_open_reader(tmp_path: Path) -> None:
    door_file = tmp_path / "door.sock"
    door_file.write_text("!DOORS;1=0;2=0;3=0;", encoding="ascii")
    any_reader = AnyDoorOpenStateReader(door_file, open_value=1)
    assert any_reader.read() is False

    door_file.write_text("!DOORS;1=0;2=1;3=0;", encoding="ascii")
    assert any_reader.read() is True
