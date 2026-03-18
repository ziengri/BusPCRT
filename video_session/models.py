from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import MetaValidationError


@dataclass(slots=True)
class SessionMeta:
    """Metadata for a recorded video session."""

    timestamp: int
    path: str
    id: str
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    codec: str = "ffv1"
    format: str = "mkv"
    frame_count: int = 0
    created_at: int | None = None
    finished_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "timestamp": self.timestamp,
            "path": self.path,
            "id": self.id,
            "codec": self.codec,
            "format": self.format,
            "frame_count": self.frame_count,
        }
        if self.width is not None:
            data["width"] = self.width
        if self.height is not None:
            data["height"] = self.height
        if self.fps is not None:
            data["fps"] = self.fps
        if self.created_at is not None:
            data["created_at"] = self.created_at
        if self.finished_at is not None:
            data["finished_at"] = self.finished_at
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMeta":
        if not isinstance(data, dict):
            raise MetaValidationError("Meta payload must be a JSON object")

        required = ("timestamp", "path", "id")
        missing = [key for key in required if key not in data]
        if missing:
            raise MetaValidationError(f"Missing required meta fields: {', '.join(missing)}")

        timestamp = data["timestamp"]
        path = data["path"]
        camera_id = data["id"]

        if not isinstance(timestamp, int):
            raise MetaValidationError("Field 'timestamp' must be int")
        if not isinstance(path, str) or not path:
            raise MetaValidationError("Field 'path' must be non-empty string")
        if not isinstance(camera_id, str) or not camera_id:
            raise MetaValidationError("Field 'id' must be non-empty string")

        return cls(
            timestamp=timestamp,
            path=path,
            id=camera_id,
            width=data.get("width"),
            height=data.get("height"),
            fps=data.get("fps"),
            codec=data.get("codec", "ffv1"),
            format=data.get("format", "mkv"),
            frame_count=int(data.get("frame_count", 0)),
            created_at=data.get("created_at"),
            finished_at=data.get("finished_at"),
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "SessionMeta":
        source = Path(path)
        try:
            with source.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise MetaValidationError(f"Failed to parse meta json: {source}") from exc
        except OSError as exc:
            raise MetaValidationError(f"Failed to read meta file: {source}") from exc
        return cls.from_dict(data)
