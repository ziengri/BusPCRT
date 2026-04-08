from __future__ import annotations

from pathlib import Path

import pytest

from app.processing.session_processor_service import SessionProcessorService
from app.shared.session_storage import SessionDirs, list_ready_meta_oldest_first
from app.shared.types import CountResult
from video_session.models import SessionMeta


class _DoorClosed:
    def read(self) -> bool:
        return False


class _DoorOpen:
    def read(self) -> bool:
        return True


class _RunnerOk:
    def __init__(self, result: CountResult):
        self.result = result

    def run_session(self, meta_path: Path) -> CountResult:
        return self.result


class _RunnerFail:
    def run_session(self, meta_path: Path) -> CountResult:
        raise RuntimeError("processing failure")


class _SinkMem:
    def __init__(self) -> None:
        self.rows = []

    def write(self, result) -> None:
        self.rows.append(result)


def _make_pair(folder: Path, ts: int, cam_id: str = "cam1") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    video_name = f"{cam_id}-{ts}.mkv"
    meta_name = f"{cam_id}-{ts}-meta.json"
    video_path = folder / video_name
    meta_path = folder / meta_name
    video_path.write_bytes(b"video")
    SessionMeta(timestamp=ts, path=video_name, id=cam_id).save(meta_path)
    return meta_path


def test_oldest_first(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    m_new = _make_pair(ready, 200)
    m_old = _make_pair(ready, 100)
    ordered = list_ready_meta_oldest_first(ready)
    assert ordered == [m_old, m_new]


def test_success_deletes_meta_and_video(tmp_path: Path) -> None:
    dirs = SessionDirs.from_root(tmp_path / "sessions")
    dirs.ensure_exists()
    meta = _make_pair(dirs.ready, 100)
    sink = _SinkMem()
    service = SessionProcessorService(
        door_reader=_DoorClosed(),
        ai_runner=_RunnerOk(CountResult(total_in=7, total_out=3, processed_frames=20)),
        result_sink=sink,
        session_dirs=dirs,
    )

    assert service.process_one_if_allowed() is True
    assert len(sink.rows) == 1
    assert sink.rows[0].total_in == 7
    assert sink.rows[0].total_out == 3
    assert not meta.exists()
    assert len(list(dirs.ready.glob("*-meta.json"))) == 0
    assert len(list(dirs.processing.glob("*-meta.json"))) == 0


def test_failure_moves_pair_to_failed(tmp_path: Path) -> None:
    dirs = SessionDirs.from_root(tmp_path / "sessions")
    dirs.ensure_exists()
    _make_pair(dirs.ready, 100)
    sink = _SinkMem()
    service = SessionProcessorService(
        door_reader=_DoorClosed(),
        ai_runner=_RunnerFail(),
        result_sink=sink,
        session_dirs=dirs,
    )

    with pytest.raises(RuntimeError):
        service.process_one_if_allowed()

    assert len(list(dirs.ready.glob("*-meta.json"))) == 0
    assert len(list(dirs.processing.glob("*-meta.json"))) == 0
    assert len(list(dirs.failed.glob("*-meta.json"))) == 1
    assert len(sink.rows) == 0


def test_processor_skips_when_door_open(tmp_path: Path) -> None:
    dirs = SessionDirs.from_root(tmp_path / "sessions")
    dirs.ensure_exists()
    meta = _make_pair(dirs.ready, 100)
    sink = _SinkMem()
    service = SessionProcessorService(
        door_reader=_DoorOpen(),
        ai_runner=_RunnerOk(CountResult(total_in=7, total_out=3, processed_frames=20)),
        result_sink=sink,
        session_dirs=dirs,
    )

    assert service.process_one_if_allowed() is False
    assert meta.exists()
    assert len(sink.rows) == 0
