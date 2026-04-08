from __future__ import annotations

from pathlib import Path

from app.door import DoorStateFilePublisher


def test_publisher_writes_true_false(tmp_path: Path) -> None:
    path = tmp_path / "door.sock"
    publisher = DoorStateFilePublisher(path)

    publisher.write(True)
    assert path.read_text(encoding="utf-8") == "true"

    publisher.write(False)
    assert path.read_text(encoding="utf-8") == "false"

