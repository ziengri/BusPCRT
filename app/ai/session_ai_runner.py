from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import people_counter_NORFAIR as norfair_app
from app.shared.types import CountResult
from video_session import SessionMeta, SessionReader


@dataclass(slots=True)
class AIRunnerConfig:
    model_path: str
    confidence: float = 0.45
    skip_frames: int = 5
    nms_topk: int = 200
    distance_threshold: float = 0.40
    hit_counter_max: int = 0
    initialization_delay: int = 1
    device: str = "CPU"
    target_width: int = 256
    line_y_ratio: float = 0.3
    ai_debug: bool = False
    ai_debug_video_each: int = 0


class SessionAIRunner:
    """Runs Norfair/OpenVINO counting on recorded session and returns totals."""

    def __init__(self, config: AIRunnerConfig):
        self.config = config
        self.detector = norfair_app.OpenVINODetector(config.model_path, device=config.device)
        self._processed_ok_counter = 0
        self._logger = logging.getLogger(__name__)

    def _should_write_debug_video(self) -> bool:
        if not self.config.ai_debug:
            return False
        each = int(self.config.ai_debug_video_each)
        next_success_index = self._processed_ok_counter + 1
        if each <= 1:
            return True
        return next_success_index % each == 0

    @staticmethod
    def _resolve_debug_video_path(meta_path: Path, meta: SessionMeta) -> Path:
        parent = meta_path.parent
        if parent.name in {"active", "ready", "processing", "failed"}:
            sessions_root = parent.parent
        else:
            sessions_root = parent
        debug_dir = sessions_root / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        return debug_dir / f"{meta.id}-{meta.timestamp}-dbg.mp4"

    def run_session(self, meta_path: str | Path) -> CountResult:
        meta_path = Path(meta_path)
        should_write_debug = self._should_write_debug_video()
        debug_video_path: Path | None = None
        debug_writer: cv2.VideoWriter | None = None

        with SessionReader(meta_path) as session_reader:
            meta = session_reader.meta
            resizer = norfair_app.FrameResizer(target_w=self.config.target_width)
            counter = norfair_app.PeopleCounter(line_y_ratio=self.config.line_y_ratio)

            total_frames = 0
            W = H = None
            tracker = None

            try:
                for frame in session_reader:
                    frame = resizer.apply(frame)
                    if W is None or H is None:
                        H, W = frame.shape[:2]
                        distance_fn = norfair_app.create_normalized_mean_euclidean_distance(height=H, width=W)
                        hit_max = (
                            self.config.hit_counter_max
                            if self.config.hit_counter_max > 0
                            else max(120, 4 * self.config.skip_frames)
                        )
                        tracker = norfair_app.Tracker(
                            distance_function=distance_fn,
                            distance_threshold=float(self.config.distance_threshold),
                            hit_counter_max=int(hit_max),
                            initialization_delay=int(self.config.initialization_delay),
                            filter_factory=norfair_app.OptimizedKalmanFilterFactory(),
                            past_detections_length=3,
                        )

                        if should_write_debug:
                            try:
                                fps_out = float(meta.fps) if meta.fps and meta.fps > 0 else 25.0
                                debug_video_path = self._resolve_debug_video_path(meta_path, meta)
                                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                                debug_writer = cv2.VideoWriter(str(debug_video_path), fourcc, fps_out, (W, H))
                                if not debug_writer.isOpened():
                                    raise RuntimeError("VideoWriter open failed")
                                self._logger.info("AI debug video enabled for session: %s", debug_video_path)
                            except Exception as exc:  # noqa: BLE001
                                self._logger.warning("Failed to initialize debug video writer: %s", exc)
                                debug_writer = None
                                debug_video_path = None

                    assert tracker is not None
                    is_det = (total_frames % self.config.skip_frames == 0)
                    rects = []
                    scores = []

                    if is_det:
                        self.detector.preprocess(frame)
                        results, _ = self.detector.infer()
                        rects, scores, _ = self.detector.postprocess(
                            results,
                            W,  # type: ignore[arg-type]
                            H,  # type: ignore[arg-type]
                            self.config.confidence,
                            self.config.nms_topk,
                        )
                        detections = norfair_app.rects_to_norfair_detections(rects, scores)
                        tracked_objects = tracker.update(detections=detections, period=self.config.skip_frames)
                    else:
                        tracked_objects = tracker.update()

                    id_centroids = norfair_app.tracked_to_id_centroids(tracked_objects)
                    counter.update_from_ids(
                        id_centroids=id_centroids,
                        H=H,  # type: ignore[arg-type]
                        is_det=is_det,
                        debug=0,
                        frame=None,
                    )

                    if debug_writer is not None and H is not None and W is not None:
                        dbg_frame = frame.copy()
                        if is_det:
                            for (x1, y1, x2, y2), conf in zip(rects, scores):
                                cv2.rectangle(dbg_frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
                                cv2.putText(
                                    dbg_frame,
                                    f"{float(conf):.2f}",
                                    (x1, max(10, y1 - 6)),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.5,
                                    (255, 255, 0),
                                    1,
                                )
                        for tid, (cx, cy) in id_centroids:
                            cv2.circle(dbg_frame, (cx, cy), 4, (0, 0, 255), -1)
                            cv2.putText(
                                dbg_frame,
                                str(tid),
                                (cx + 4, cy - 4),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.5,
                                (0, 0, 255),
                                1,
                            )
                        line_y = counter.get_line_y(H)
                        cv2.line(dbg_frame, (0, line_y), (W, line_y), (0, 255, 255), 2)
                        cv2.putText(
                            dbg_frame,
                            f"In: {counter.totalDown} Out: {counter.totalUp}",
                            (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.7,
                            (0, 255, 0),
                            2,
                        )
                        debug_writer.write(dbg_frame)

                    total_frames += 1
            finally:
                if debug_writer is not None:
                    debug_writer.release()

        self._processed_ok_counter += 1
        if debug_video_path is not None:
            self._logger.info("AI debug video saved: %s", debug_video_path)
        return CountResult(
            total_in=counter.totalDown,
            total_out=counter.totalUp,
            processed_frames=total_frames,
            debug_video_path=debug_video_path,
        )
