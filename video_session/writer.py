from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .models import SessionMeta
from .utils import (
    FFmpegProcessError,
    SessionError,
    atomic_replace,
    build_session_basename,
    current_timestamp_ms,
)


class SessionWriter:
    """Write OpenCV BGR frames into MKV(FFV1) and generate meta.json."""

    def __init__(
        self,
        output_dir: str | Path,
        camera_id: str,
        width: int,
        height: int,
        fps: int = 25,
        ffmpeg_bin: str = "ffmpeg",
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.camera_id = camera_id
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.ffmpeg_bin = ffmpeg_bin

        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.fps <= 0:
            raise ValueError("fps must be positive")

        self.start_timestamp = current_timestamp_ms()
        self.created_at = self.start_timestamp
        self.base_name = build_session_basename(self.camera_id, self.start_timestamp)
        self._video_path = self.output_dir / f"{self.base_name}.mkv"
        self._meta_path = self.output_dir / f"{self.base_name}-meta.json"
        self._video_tmp_path = self._video_path.with_suffix(self._video_path.suffix + ".tmp")
        self._meta_tmp_path = self._meta_path.with_suffix(self._meta_path.suffix + ".tmp")

        self._frame_count = 0
        self._closed = False
        self._process = self._start_ffmpeg()

    @property
    def video_path(self) -> Path:
        return self._video_path

    @property
    def meta_path(self) -> Path:
        return self._meta_path

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def _start_ffmpeg(self) -> subprocess.Popen[bytes]:
        cmd = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "bgr24",
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            str(self.fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "ffv1",
            "-f",
            "matroska",
            str(self._video_tmp_path),
        ]
        try:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise FFmpegProcessError(f"Failed to start ffmpeg with command: {' '.join(cmd)}") from exc

    def write_frame(self, frame: np.ndarray) -> None:
        if self._closed:
            raise SessionError("SessionWriter is already closed")
        if frame.dtype != np.uint8:
            raise ValueError(f"Invalid frame dtype: {frame.dtype}; expected uint8")
        if frame.shape != (self.height, self.width, 3):
            raise ValueError(
                f"Invalid frame shape: {frame.shape}; expected ({self.height}, {self.width}, 3)"
            )

        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        stdin = self._process.stdin
        if stdin is None:
            raise FFmpegProcessError("ffmpeg stdin is not available")

        try:
            stdin.write(frame.tobytes())
        except BrokenPipeError as exc:
            raise FFmpegProcessError(self._format_ffmpeg_error("Broken ffmpeg pipe while writing frame")) from exc

        self._frame_count += 1

    def _read_process_stderr(self) -> str:
        stderr = self._process.stderr
        if stderr is None:
            return ""
        if self._process.poll() is None:
            return ""
        try:
            raw = stderr.read()
        except Exception:  # noqa: BLE001
            return ""
        if not raw:
            return ""
        return raw.decode("utf-8", errors="replace").strip()

    def _format_ffmpeg_error(self, message: str) -> str:
        stderr_text = self._read_process_stderr()
        if stderr_text:
            return f"{message}. ffmpeg stderr: {stderr_text}"
        return message

    def close(self) -> Path:
        if self._closed:
            return self._meta_path

        stdin = self._process.stdin
        if stdin is not None:
            try:
                stdin.close()
            except Exception:  # noqa: BLE001
                pass

        return_code = self._process.wait()
        if return_code != 0:
            self._cleanup_tmp_files()
            raise FFmpegProcessError(self._format_ffmpeg_error(f"ffmpeg exited with code {return_code}"))

        atomic_replace(self._video_tmp_path, self._video_path)

        finished_at = current_timestamp_ms()
        meta = SessionMeta(
            timestamp=self.start_timestamp,
            path=self._video_path.name,
            id=self.camera_id,
            width=self.width,
            height=self.height,
            fps=self.fps,
            codec="ffv1",
            format="mkv",
            frame_count=self._frame_count,
            created_at=self.created_at,
            finished_at=finished_at,
        )
        meta.save(self._meta_tmp_path)
        atomic_replace(self._meta_tmp_path, self._meta_path)

        self._closed = True
        return self._meta_path

    def _cleanup_tmp_files(self) -> None:
        for tmp_path in (self._video_tmp_path, self._meta_tmp_path):
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    def __enter__(self) -> "SessionWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._closed:
            try:
                self.close()
            except Exception:  # noqa: BLE001
                self._cleanup_tmp_files()
                if exc_type is None:
                    raise
