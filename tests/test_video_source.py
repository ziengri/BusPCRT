from __future__ import annotations

from app.recording.video_source import OpenCVVideoSource


class _ClosedCapture:
    def isOpened(self) -> bool:
        return False

    def read(self):
        return False, None

    def release(self) -> None:
        return None


def test_live_source_unavailable_does_not_raise(monkeypatch) -> None:
    monkeypatch.setattr("app.recording.video_source.cv2.VideoCapture", lambda *_args, **_kwargs: _ClosedCapture())

    source = OpenCVVideoSource("rtsp://cam1", reconnect_interval_s=0.1)

    assert source.read() is None
    assert source.exhausted is False
