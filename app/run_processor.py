from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ai import AIRunnerConfig, SessionAIRunner
from app.door import ProcessorDoorStateReader
from app.processing import CombinedResultSink, CsvResultSink, SessionProcessorService, TimelineApiResultSink
from app.shared import SessionDirs
from app.utils import install_exception_logging, setup_logger


def _env_defaults(env_file: str | None) -> dict[str, object]:
    if not env_file:
        return {}
    path = Path(env_file)
    if not path.exists():
        return {}
    raw = dotenv_values(path)
    return {
        "model": raw.get("MODEL_PATH"),
        "sessions_dir": raw.get("SESSIONS_DIR"),
        "zmq_ipc_endpoint": raw.get("ZMQ_IPC_ENDPOINT"),
        "csv": raw.get("CSV_PATH"),
        "timeline_url": raw.get("TIMELINE_URL"),
        "bus_id": raw.get("BUS_ID"),
        "api_timeout": raw.get("API_TIMEOUT"),
        "idle_sleep": raw.get("IDLE_SLEEP"),
        "confidence": raw.get("CONFIDENCE"),
        "skip_frames": raw.get("SKIP_FRAMES"),
        "nms_topk": raw.get("NMS_TOPK"),
        "dist_th": raw.get("DIST_TH"),
        "hit_max": raw.get("HIT_MAX"),
        "init_delay": raw.get("INIT_DELAY"),
        "device": raw.get("DEVICE"),
        "target_width": raw.get("TARGET_WIDTH"),
        "line_y_ratio": raw.get("LINE_Y_RATIO"),
        "ai_debug": raw.get("AI_DEBUG"),
        "ai_debug_video_each": raw.get("AI_DEBUG_VIDEO_EACH"),
    }


def parse_args() -> argparse.Namespace:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", default="processor.env")
    pre_args, _ = pre.parse_known_args()
    env = _env_defaults(pre_args.env_file)

    parser = argparse.ArgumentParser(description="Oldest-first session processor process")
    parser.add_argument("--env-file", default=pre_args.env_file)
    parser.add_argument("--model", default=None)
    parser.add_argument("--sessions-dir", default="sessions")
    parser.add_argument("--zmq-ipc-endpoint", dest="zmq_ipc_endpoint", default="ipc:///run/atom/doors.sock")
    parser.add_argument("--csv", default="results.csv")
    parser.add_argument("--timeline-url", default="http://5.129.252.183:8000/api/v1/timeline")
    parser.add_argument("--bus-id", dest="bus_id", default="BUS320")
    parser.add_argument("--api-timeout", dest="api_timeout", type=float, default=10.0)
    parser.add_argument("--idle-sleep", dest="idle_sleep", type=float, default=0.1)
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--skip-frames", dest="skip_frames", type=int, default=5)
    parser.add_argument("--nms-topk", dest="nms_topk", type=int, default=200)
    parser.add_argument("--dist-th", dest="dist_th", type=float, default=0.40)
    parser.add_argument("--hit-max", dest="hit_max", type=int, default=0)
    parser.add_argument("--init-delay", dest="init_delay", type=int, default=1)
    parser.add_argument("--device", default="CPU")
    parser.add_argument("--target-width", dest="target_width", type=int, default=256)
    parser.add_argument("--line-y-ratio", dest="line_y_ratio", type=float, default=0.3)
    parser.add_argument("--ai-debug", dest="ai_debug", type=int, default=0)
    parser.add_argument("--ai-debug-video-each", dest="ai_debug_video_each", type=int, default=0)
    parser.set_defaults(**{k: v for k, v in env.items() if v not in (None, "")})

    args = parser.parse_args()
    if not args.model:
        parser.error("--model is required (CLI or env)")
    return args


def main() -> int:
    args = parse_args()
    setup_logger("processor")
    install_exception_logging()

    door_reader = ProcessorDoorStateReader(endpoint=args.zmq_ipc_endpoint)
    session_dirs = SessionDirs.from_root(args.sessions_dir)
    result_sink = CombinedResultSink(
        TimelineApiResultSink(
            url=args.timeline_url,
            bus=args.bus_id,
            timeout_s=float(args.api_timeout),
        ),
        CsvResultSink(args.csv),
    )
    ai_runner = SessionAIRunner(
        AIRunnerConfig(
            model_path=args.model,
            confidence=float(args.confidence),
            skip_frames=int(args.skip_frames),
            nms_topk=int(args.nms_topk),
            distance_threshold=float(args.dist_th),
            hit_counter_max=int(args.hit_max),
            initialization_delay=int(args.init_delay),
            device=args.device,
            target_width=int(args.target_width),
            line_y_ratio=float(args.line_y_ratio),
            ai_debug=bool(int(args.ai_debug)),
            ai_debug_video_each=int(args.ai_debug_video_each),
        )
    )

    service = SessionProcessorService(
        door_reader=door_reader,
        ai_runner=ai_runner,
        result_sink=result_sink,
        session_dirs=session_dirs,
        idle_sleep_s=float(args.idle_sleep),
    )
    service.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
