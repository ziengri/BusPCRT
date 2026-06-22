from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


class OpenCVVideoSource:
    """Unified OpenCV source for file/rtsp/webcam."""

    def __init__(self, source: str, reconnect_interval_s: float = 5.0):
        self._logger = logging.getLogger(__name__)
        self._source = source
        self._is_file = Path(source).exists()
        self._exhausted = False
        self._reconnect_interval_s = max(0.1, float(reconnect_interval_s))
        self._last_open_attempt_at = 0.0
        self._stream_unavailable_logged = False

        if source.isdigit():
            cap_source: int | str = int(source)
        else:
            cap_source = source

        self._cap_source = cap_source
        self._cap: cv2.VideoCapture | None = None
        if not self._open_capture():
            raise RuntimeError(f"Failed to open video source: {source}")

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def is_file(self) -> bool:
        return self._is_file

    def _open_capture(self) -> bool:
        self._last_open_attempt_at = time.monotonic()
        cap = cv2.VideoCapture(self._cap_source)
        if cap.isOpened():
            self._cap = cap
            self._exhausted = False
            if self._stream_unavailable_logged:
                self._logger.info("Camera stream recovered: %s", self._source)
                self._stream_unavailable_logged = False
            return True

        cap.release()
        self._cap = None
        if self._is_file:
            return False
        if not self._stream_unavailable_logged:
            self._logger.warning("Camera stream unavailable: %s", self._source)
            self._stream_unavailable_logged = True
        return True

    def _reconnect_if_due(self) -> None:
        if self._cap is not None or self._is_file:
            return
        if (time.monotonic() - self._last_open_attempt_at) < self._reconnect_interval_s:
            return
        self._open_capture()

    def read(self) -> Optional[np.ndarray]:
        if self._cap is None:
            self._reconnect_if_due()
            return None

        ok, frame = self._cap.read()
        if not ok:
            if self._is_file:
                self._exhausted = True
            else:
                self._cap.release()
                self._cap = None
                if not self._stream_unavailable_logged:
                    self._logger.warning("Camera stream unavailable: %s", self._source)
                    self._stream_unavailable_logged = True
                self._reconnect_if_due()
            return None
        return frame

    def reset(self) -> bool:
        """Reopen file source from the beginning."""
        if not self._is_file:
            return False
        if self._cap is not None:
            self._cap.release()
        self._cap = cv2.VideoCapture(self._cap_source)
        self._exhausted = not self._cap.isOpened()
        return not self._exhausted

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
