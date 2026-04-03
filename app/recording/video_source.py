from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np


class OpenCVVideoSource:
    """Unified OpenCV source for file/rtsp/webcam."""

    def __init__(self, source: str):
        self._is_file = Path(source).exists()
        self._exhausted = False

        if source.isdigit():
            cap_source: int | str = int(source)
        else:
            cap_source = source

        self._cap = cv2.VideoCapture(cap_source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open video source: {source}")

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    def read(self) -> Optional[np.ndarray]:
        ok, frame = self._cap.read()
        if not ok:
            if self._is_file:
                self._exhausted = True
            return None
        return frame

    def release(self) -> None:
        self._cap.release()
