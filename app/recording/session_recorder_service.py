from __future__ import annotations

import time
from pathlib import Path

import cv2
import logging
from app.recording.video_source import OpenCVVideoSource
from app.shared.session_storage import SessionDirs, move_session_pair
from video_session import SessionWriter


class SessionRecorderService:
    """Continuously records fixed-size sessions and moves them to ready."""

    def __init__(
        self,
        source: OpenCVVideoSource,
        session_dirs: SessionDirs,
        camera_id: str,
        width: int,
        height: int,
        fps: int = 25,
        session_duration_s: int = 30,
        idle_sleep_s: float = 0.05,
    ):
        self.source = source
        self.session_dirs = session_dirs
        self.camera_id = camera_id
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.session_duration_s = int(session_duration_s)
        self.idle_sleep_s = float(idle_sleep_s)

        self.session_dirs.ensure_exists()
        self._writer: SessionWriter | None = None
        self._logger = logging.getLogger(__name__)
        self._current_session_frames = 0
        self._frames_per_session = max(1, self.fps * self.session_duration_s)

    def _open_writer(self) -> None:
        self._writer = SessionWriter(
            output_dir=self.session_dirs.active,
            camera_id=self.camera_id,
            width=self.width,
            height=self.height,
            fps=self.fps,
        )
        self._current_session_frames = 0

    def _close_writer_to_ready(self) -> Path | None:
        if self._writer is None:
            return None
        self._logger.debug("Close writer. File:%s", self._writer.base_name)
        meta_path = self._writer.close()
        self._writer = None
        self._current_session_frames = 0
        return move_session_pair(meta_path, self.session_dirs.ready)

    def _write_frame(self, frame) -> None:
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
        assert self._writer is not None
        self._writer.write_frame(frame)

    def run_forever(self) -> None:
        try:
            self._logger.info(
                "Starting recorder, segment_seconds=%s, frames_per_segment=%s",
                self.session_duration_s,
                self._frames_per_session,
            )
            while True:
                frame = self.source.read()

                if frame is None:
                    if self.source.exhausted:
                        self._close_writer_to_ready()
                        break
                    time.sleep(self.idle_sleep_s)
                    continue

                if self._writer is None:
                    self._open_writer()
                    self._logger.debug("Start writer")

                self._write_frame(frame)
                self._current_session_frames += 1
                if self._current_session_frames >= self._frames_per_session:
                    self._close_writer_to_ready()
        finally:
            try:
                self._close_writer_to_ready()
                self._logger.info("Closing recorder")
            except Exception:  # noqa: BLE001
                pass
            self.source.release()
