from __future__ import annotations

from pathlib import Path

from app.door.door_state_reader import DoorStateReader


def test_true_false_case_insensitive(tmp_path: Path) -> None:
    sock = tmp_path / "door.sock"
    reader = DoorStateReader(sock, initial_state=False)

    sock.write_text("TrUe", encoding="utf-8")
    assert reader.read() is True

    sock.write_text("FALSE", encoding="utf-8")
    assert reader.read() is False


def test_missing_or_invalid_uses_last_known(tmp_path: Path) -> None:
    sock = tmp_path / "door.sock"
    reader = DoorStateReader(sock, initial_state=False)

    sock.write_text("true", encoding="utf-8")
    assert reader.read() is True

    sock.write_text("invalid", encoding="utf-8")
    assert reader.read() is True

    sock.unlink()
    assert reader.read() is True
