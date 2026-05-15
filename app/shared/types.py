from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CountResult:
    total_in: int
    total_out: int
    processed_frames: int = 0
    debug_video_path: Path | None = None


@dataclass
class ProcessedResult:
    date: str
    id: str
    total_in: int
    total_out: int
    meta_path: Path
