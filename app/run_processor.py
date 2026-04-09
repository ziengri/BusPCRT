from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ai import AIRunnerConfig, SessionAIRunner
from app.door import AnyDoorOpenStateReader
from app.processing import CombinedResultSink, CsvResultSink, SessionProcessorService, TimelineApiResultSink
from app.shared import SessionDirs
from app.utils import install_exception_logging, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oldest-first session processor process")
    parser.add_argument("--config", default=None, help="Path to processor JSON config file")
    parser.add_argument(
        "--door-rs232-config",
        dest="door_rs232_config",
        default="door_rs232_config.json",
        help="Path to shared RS232 JSON config file",
    )
    parser.add_argument("--model", default=None, help="Path to OpenVINO model .xml")
    parser.add_argument("--sessions-dir", default="sessions", help="Root for active/ready/processing/failed")
    parser.add_argument("--door-sock", default="door.sock", help="Path to door state file")
    parser.add_argument("--door-open-value", dest="door_open_value", type=int, default=1)
    parser.add_argument("--csv", default="results.csv", help="Output CSV file")
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
    return parser


def _load_config(path: str, parser: argparse.ArgumentParser) -> dict[str, object]:
    cfg_path = Path(path)
    try:
        raw = cfg_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except OSError as exc:
        parser.error(f"Failed to read config file '{cfg_path}': {exc}")
    except json.JSONDecodeError as exc:
        parser.error(f"Failed to parse JSON config '{cfg_path}': {exc}")

    if not isinstance(payload, dict):
        parser.error(f"Config file '{cfg_path}' must contain a JSON object")

    normalized: dict[str, object] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            parser.error("All config keys must be strings")
        normalized[key.replace("-", "_")] = value
    return normalized


def parse_args() -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=None)
    pre_parser.add_argument("--door-rs232-config", dest="door_rs232_config", default="door_rs232_config.json")
    pre_args, _ = pre_parser.parse_known_args()

    parser = _build_parser()

    if pre_args.door_rs232_config and Path(pre_args.door_rs232_config).exists():
        shared_config = _load_config(pre_args.door_rs232_config, parser)
        valid_keys = {action.dest for action in parser._actions}
        filtered_shared = {k: v for k, v in shared_config.items() if k in valid_keys}
        parser.set_defaults(**filtered_shared)

    if pre_args.config:
        processor_config = _load_config(pre_args.config, parser)
        valid_keys = {action.dest for action in parser._actions}
        unknown = sorted(k for k in processor_config if k not in valid_keys)
        if unknown:
            parser.error(f"Unknown keys in processor config: {', '.join(unknown)}")
        parser.set_defaults(**processor_config)

    args = parser.parse_args()
    if not args.model:
        parser.error("Argument '--model' is required (CLI or config)")
    return args


def main() -> int:
    args = parse_args()
    setup_logger("processor")
    install_exception_logging()

    door_reader = AnyDoorOpenStateReader(
        path=args.door_sock,
        open_value=args.door_open_value,
    )
    session_dirs = SessionDirs.from_root(args.sessions_dir)
    result_sink = CombinedResultSink(
        TimelineApiResultSink(
            url=args.timeline_url,
            bus=args.bus_id,
            timeout_s=args.api_timeout,
        ),
        CsvResultSink(args.csv),
    )
    ai_runner = SessionAIRunner(
        AIRunnerConfig(
            model_path=args.model,
            confidence=args.confidence,
            skip_frames=args.skip_frames,
            nms_topk=args.nms_topk,
            distance_threshold=args.dist_th,
            hit_counter_max=args.hit_max,
            initialization_delay=args.init_delay,
            device=args.device,
            target_width=args.target_width,
            line_y_ratio=args.line_y_ratio,
        )
    )

    service = SessionProcessorService(
        door_reader=door_reader,
        ai_runner=ai_runner,
        result_sink=result_sink,
        session_dirs=session_dirs,
        idle_sleep_s=args.idle_sleep,
    )
    service.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
