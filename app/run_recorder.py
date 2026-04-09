from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.door import ChannelDoorStateReader
from app.recording import OpenCVVideoSource, SessionRecorderService
from app.shared import SessionDirs
from app.utils import install_exception_logging, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Door-gated recorder process")
    parser.add_argument("--config", default=None, help="Path to recorder JSON config file")
    parser.add_argument(
        "--door-rs232-config",
        dest="door_rs232_config",
        default="door_rs232_config.json",
        help="Path to shared RS232 JSON config file",
    )
    parser.add_argument("--source", default=None, help="RTSP/file/camera source for cv2.VideoCapture")
    parser.add_argument("--camera-id", dest="camera_id", default=None, help="Camera id")
    parser.add_argument("--sessions-dir", default="sessions", help="Root for active/ready/processing/failed")
    parser.add_argument("--door-sock", default="door.sock", help="Path to door state file")
    parser.add_argument("--door-channel", dest="door_channel", type=int, default=None, help="Door channel for this recorder")
    parser.add_argument("--door-open-value", dest="door_open_value", type=int, default=1)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--idle-sleep", dest="idle_sleep", type=float, default=0.05)
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
        recorder_config = _load_config(pre_args.config, parser)
        valid_keys = {action.dest for action in parser._actions}
        unknown = sorted(k for k in recorder_config if k not in valid_keys)
        if unknown:
            parser.error(f"Unknown keys in recorder config: {', '.join(unknown)}")
        parser.set_defaults(**recorder_config)

    args = parser.parse_args()
    if not args.source:
        parser.error("Argument '--source' is required (CLI or config)")
    if not args.camera_id:
        parser.error("Argument '--camera-id' is required (CLI or config)")
    if args.door_channel is None:
        parser.error("Argument '--door-channel' is required (CLI or recorder config)")
    return args


def main() -> int:
    args = parse_args()
    setup_logger(args.camera_id)
    install_exception_logging()

    source = OpenCVVideoSource(args.source)
    session_dirs = SessionDirs.from_root(args.sessions_dir)
    door_reader = ChannelDoorStateReader(
        path=args.door_sock,
        door_channel=args.door_channel,
        open_value=args.door_open_value,
    )

    service = SessionRecorderService(
        source=source,
        door_reader=door_reader,
        session_dirs=session_dirs,
        camera_id=args.camera_id,
        width=args.width,
        height=args.height,
        fps=args.fps,
        idle_sleep_s=args.idle_sleep,
    )
    service.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
