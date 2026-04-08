from __future__ import annotations

from pathlib import Path

import numpy as np

import app.recording.session_recorder_service as recorder_module
from app.recording.session_recorder_service import SessionRecorderService
from app.shared.session_storage import SessionDirs
from video_session.models import SessionMeta


class _DoorSequenceReader:
    def __init__(self, states: list[bool]):
        self._states = states
        self._idx = 0

    def read(self) -> bool:
        if self._idx >= len(self._states):
            return self._states[-1]
        state = self._states[self._idx]
        self._idx += 1
        return state

    def close(self) -> None:
        return None


class _SourceSequence:
    def __init__(self, frames: list[np.ndarray]):
        self._frames = list(frames)
        self.exhausted = False
        self.released = False

    def read(self):
        if self._frames:
            return self._frames.pop(0)
        self.exhausted = True
        return None

    def release(self) -> None:
        self.released = True


class _FakeWriter:
    def __init__(self, output_dir, camera_id, width, height, fps):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.camera_id = camera_id
        self.base_name = f"{camera_id}-1000"
        self._video_name = f"{self.base_name}.mkv"
        self._meta_name = f"{self.base_name}-meta.json"
        self._frame_count = 0

    def write_frame(self, frame) -> None:
        self._frame_count += 1

    def close(self) -> Path:
        video_path = self.output_dir / self._video_name
        meta_path = self.output_dir / self._meta_name
        video_path.write_bytes(b"video")
        SessionMeta(
            timestamp=1000,
            path=self._video_name,
            id=self.camera_id,
            frame_count=self._frame_count,
        ).save(meta_path)
        return meta_path


def test_recorder_open_close_creates_ready_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recorder_module, "SessionWriter", _FakeWriter)

    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    source = _SourceSequence([frame, frame, frame])
    door = _DoorSequenceReader([True, True, False, False])
    dirs = SessionDirs.from_root(tmp_path / "sessions")

    service = SessionRecorderService(
        source=source,
        door_reader=door,
        session_dirs=dirs,
        camera_id="cam1",
        width=16,
        height=16,
        fps=25,
        idle_sleep_s=0.0,
    )
    service.run_forever()

    ready_metas = list(dirs.ready.glob("*-meta.json"))
    assert len(ready_metas) == 1
    meta = SessionMeta.load(ready_metas[0])
    assert meta.frame_count == 2
    assert (dirs.ready / meta.path).exists()
    assert source.released is True

