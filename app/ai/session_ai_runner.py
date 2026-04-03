from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import people_counter_NORFAIR as norfair_app
from app.shared.types import CountResult
from video_session import SessionReader


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


class SessionAIRunner:
    """Runs Norfair/OpenVINO counting on recorded session and returns totals."""

    def __init__(self, config: AIRunnerConfig):
        self.config = config
        self.detector = norfair_app.OpenVINODetector(config.model_path, device=config.device)

    def run_session(self, meta_path: str | Path) -> CountResult:
        with SessionReader(meta_path) as session_reader:
            resizer = norfair_app.FrameResizer(target_w=self.config.target_width)
            counter = norfair_app.PeopleCounter(line_y_ratio=self.config.line_y_ratio)

            total_frames = 0
            W = H = None
            tracker = None

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

                assert tracker is not None
                is_det = (total_frames % self.config.skip_frames == 0)

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
                total_frames += 1

        return CountResult(
            total_in=counter.totalDown,
            total_out=counter.totalUp,
            processed_frames=total_frames,
        )
