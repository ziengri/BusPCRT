from __future__ import annotations

import os
import time
from pathlib import Path


class SessionError(Exception):
    """Base exception for video session errors."""


class FFmpegProcessError(SessionError):
    """Raised when ffmpeg process fails."""


class MetaValidationError(SessionError):
    """Raised when meta.json is invalid."""


def current_timestamp_ms() -> int:
    """Return current Unix timestamp in milliseconds."""
    return int(time.time() * 1000)


def build_session_basename(camera_id: str, timestamp_ms: int) -> str:
    """Build base file name: {camera_id}-{timestamp}."""
    camera_id = (camera_id or "").strip()
    if not camera_id:
        raise ValueError("camera_id must be a non-empty string")
    if any(ch in camera_id for ch in ("/", "\\", ":", "\x00")):
        raise ValueError("camera_id contains unsupported characters")
    return f"{camera_id}-{timestamp_ms}"


def atomic_replace(src: Path, dst: Path) -> None:
    """Atomically replace destination with source."""
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def resolve_video_path(meta_path: Path, stored_path: str) -> Path:
    """Resolve video path stored in meta. Relative path is resolved from meta directory."""
    candidate = Path(stored_path)
    if candidate.is_absolute():
        return candidate
    return (meta_path.parent / candidate).resolve()
