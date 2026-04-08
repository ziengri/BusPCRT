from __future__ import annotations

import os
from pathlib import Path


class DoorStateFilePublisher:
    """Publishes boolean door state into file as 'true'/'false'."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, state: bool) -> None:
        value = "true" if state else "false"
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(value, encoding="utf-8")
        os.replace(tmp_path, self.path)

