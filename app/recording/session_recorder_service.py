from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

import cv2
import logging
from app.recording.video_source import OpenCVVideoSource
from app.shared.session_storage import SessionDirs, delete_session_pair, move_session_pair
from video_session import SessionWriter


class DoorReader(Protocol):
    def read(self) -> bool:
        ...

    def close(self) -> None:
        ...


class SessionRecorderService:
    """Records frames only while door is open; finalizes on close."""

    def __init__(
        self,
        source: OpenCVVideoSource,
        door_reader: DoorReader,
        session_dirs: SessionDirs,
        camera_id: str,
        width: int,
        height: int,
        fps: int = 25,
        max_session_seconds: float = 300.0,
        idle_sleep_s: float = 0.05,
    ):
        self.source = source
        self.door_reader = door_reader
        self.session_dirs = session_dirs
        self.camera_id = camera_id
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.max_session_seconds = float(max_session_seconds)
        self.idle_sleep_s = float(idle_sleep_s)
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.max_session_seconds <= 0:
            raise ValueError("max_session_seconds must be positive")
        self._max_frames_allowed = int(self.max_session_seconds * self.fps)

        self.session_dirs.ensure_exists()
        self._writer: SessionWriter | None = None
        self._skip_until_door_close = False
        self._logger = logging.getLogger(__name__)

    def _open_writer(self) -> None:
        self._writer = SessionWriter(
            output_dir=self.session_dirs.active,
            camera_id=self.camera_id,
            width=self.width,
            height=self.height,
            fps=self.fps,
        )

    def _close_writer_to_ready(self) -> Path | None:
        if self._writer is None:
            return None
        self._logger.debug("Close writer. File:%s", self._writer.base_name)
        meta_path = self._writer.close()
        self._writer = None
        return move_session_pair(meta_path, self.session_dirs.ready)

    def _close_writer_and_discard(self) -> None:
        if self._writer is None:
            return
        self._logger.warning("Discard overlong session. File:%s", self._writer.base_name)
        meta_path = self._writer.close()
        self._writer = None
        delete_session_pair(meta_path)

    def _write_frame(self, frame) -> None:
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
        assert self._writer is not None
        self._writer.write_frame(frame)

    def _is_over_limit(self) -> bool:
        if self._writer is None:
            return False
        return self._writer.frame_count > self._max_frames_allowed

    def run_forever(self) -> None:
        try:
            self._logger.info("Starting recorder in door-gated mode")
            while True:
                door_open = self.door_reader.read()
                if not door_open:
                    if self._writer is not None:
                        self._close_writer_to_ready()
                    if self._skip_until_door_close:
                        self._skip_until_door_close = False
                        self._logger.info("Door closed, overlong-session skip mode disabled")

                frame = self.source.read()

                if frame is None:
                    if self.source.exhausted:
                        self._logger.info("Source exhausted, restarting from beginning")
                        self._close_writer_to_ready()
                        if not self.source.reset():
                            self._logger.error("Failed to restart exhausted source, stopping recorder")
                            break
                    time.sleep(self.idle_sleep_s)
                    continue

                if door_open:
                    if self._skip_until_door_close:
                        continue
                    if self._writer is None:
                        self._open_writer()
                        self._logger.debug("Start writer")
                    self._write_frame(frame)
                    if self._is_over_limit():
                        writer = self._writer
                        assert writer is not None
                        approx_seconds = writer.frame_count / float(self.fps)
                        self._logger.warning(
                            "Session exceeded max duration and will be discarded. camera=%s frames=%s seconds=%.2f limit_s=%.2f",
                            self.camera_id,
                            writer.frame_count,
                            approx_seconds,
                            self.max_session_seconds,
                        )
                        self._close_writer_and_discard()
                        self._skip_until_door_close = True
        finally:
            try:
                self._close_writer_to_ready()
                self._logger.info("Closing recorder")
            except Exception:  # noqa: BLE001
                pass
            try:
                self.door_reader.close()
            except Exception:  # noqa: BLE001
                pass
            self.source.release()
