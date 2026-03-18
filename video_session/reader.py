from __future__ import annotations

from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from .models import SessionMeta
from .utils import SessionError, resolve_video_path


class SessionReader:
    """Read video frames sequentially using meta.json file."""

    def __init__(self, meta_path: str | Path):
        self.meta_path = Path(meta_path)
        self.meta = SessionMeta.load(self.meta_path)
        self.video_path = resolve_video_path(self.meta_path, self.meta.path)

        self._cap = cv2.VideoCapture(str(self.video_path))
        if not self._cap.isOpened():
            raise SessionError(f"Failed to open video file: {self.video_path}")

    def read_frame(self) -> np.ndarray | None:
        ok, frame = self._cap.read()
        if not ok:
            return None
        return frame

    def __iter__(self) -> Iterator[np.ndarray]:
        while True:
            frame = self.read_frame()
            if frame is None:
                break
            yield frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()

    def __enter__(self) -> "SessionReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
