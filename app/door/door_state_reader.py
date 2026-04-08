from __future__ import annotations

from pathlib import Path


class DoorStateReader:
    """Reads door state from file with 'true'/'false' values."""

    def __init__(self, path: str | Path = "door.sock", initial_state: bool = False):
        self.path = Path(path)
        self._last_state = bool(initial_state)

    def read(self) -> bool:
        try:
            raw = self.path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            return self._last_state

        if raw == "true":
            self._last_state = True
        elif raw == "false":
            self._last_state = False
        return self._last_state

    def close(self) -> None:
        return None
