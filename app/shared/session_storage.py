from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from video_session import SessionMeta
from video_session.utils import resolve_video_path


@dataclass
class SessionDirs:
    root: Path
    active: Path
    ready: Path
    processing: Path
    failed: Path
    saved: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "SessionDirs":
        root_path = Path(root)
        return cls(
            root=root_path,
            active=root_path / "active",
            ready=root_path / "ready",
            processing=root_path / "processing",
            failed=root_path / "failed",
            saved=root_path / "saved",
        )

    def ensure_exists(self) -> None:
        for path in (self.root, self.active, self.ready, self.processing, self.failed, self.saved):
            path.mkdir(parents=True, exist_ok=True)


def list_ready_meta_oldest_first(ready_dir: Path) -> list[Path]:
    metas = list(ready_dir.glob("*-meta.json"))

    def sort_key(path: Path) -> tuple[int, str]:
        try:
            meta = SessionMeta.load(path)
            return int(meta.timestamp), path.name
        except Exception:  # noqa: BLE001
            return 2**63 - 1, path.name

    return sorted(metas, key=sort_key)


def resolve_session_pair(meta_path: Path) -> tuple[Path, Path]:
    meta = SessionMeta.load(meta_path)
    video_path = resolve_video_path(meta_path, meta.path)
    return meta_path, video_path


def move_session_pair(meta_path: Path, target_dir: Path) -> Path:
    meta_path, video_path = resolve_session_pair(meta_path)
    target_dir.mkdir(parents=True, exist_ok=True)

    target_video = target_dir / video_path.name
    target_meta = target_dir / meta_path.name

    os.replace(video_path, target_video)
    os.replace(meta_path, target_meta)
    return target_meta


def delete_session_pair(meta_path: Path) -> None:
    meta_path, video_path = resolve_session_pair(meta_path)
    if video_path.exists():
        video_path.unlink()
    if meta_path.exists():
        meta_path.unlink()
