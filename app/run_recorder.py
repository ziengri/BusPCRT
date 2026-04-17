from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.door import RecorderDoorStateReader
from app.recording import OpenCVVideoSource, SessionRecorderService
from app.shared import SessionDirs
from app.utils import install_exception_logging, setup_logger


def _load_env(path_value: str | None) -> dict[str, object]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v not in (None, "")}


def _env_defaults(env_file: str | None, config_env_file: str | None) -> dict[str, object]:
    raw: dict[str, object] = {}
    raw.update(_load_env(config_env_file))
    raw.update(_load_env(env_file))
    return {
        "source": raw.get("SOURCE"),
        "camera_id": raw.get("CAMERA_ID"),
        "sessions_dir": raw.get("SESSIONS_DIR"),
        "zmq_ipc_endpoint": raw.get("ZMQ_IPC_ENDPOINT"),
        "door_channel": raw.get("DOOR_CHANNEL"),
        "door_open_value": raw.get("DOOR_OPEN_VALUE"),
        "width": raw.get("WIDTH"),
        "height": raw.get("HEIGHT"),
        "fps": raw.get("FPS"),
        "idle_sleep": raw.get("IDLE_SLEEP"),
    }


def parse_args() -> argparse.Namespace:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config-env-file", default="config.env")
    pre.add_argument("--env-file", default="recorder.env")
    pre_args, _ = pre.parse_known_args()
    env = _env_defaults(pre_args.env_file, pre_args.config_env_file)

    parser = argparse.ArgumentParser(description="Door-gated recorder process")
    parser.add_argument("--config-env-file", default=pre_args.config_env_file)
    parser.add_argument("--env-file", default=pre_args.env_file)
    parser.add_argument("--source", default=None)
    parser.add_argument("--camera-id", dest="camera_id", default=None)
    parser.add_argument("--sessions-dir", default="sessions")
    parser.add_argument("--zmq-ipc-endpoint", dest="zmq_ipc_endpoint", default="ipc:///run/atom/doors.sock")
    parser.add_argument("--door-channel", dest="door_channel", type=int, default=None)
    parser.add_argument("--door-open-value", dest="door_open_value", type=int, default=1)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--idle-sleep", dest="idle_sleep", type=float, default=0.05)
    parser.set_defaults(**{k: v for k, v in env.items() if v not in (None, "")})

    args = parser.parse_args()
    if not args.source:
        parser.error("--source is required (CLI or env)")
    if not args.camera_id:
        parser.error("--camera-id is required (CLI or env)")
    if args.door_channel is None:
        parser.error("--door-channel is required (CLI or env)")
    return args


def main() -> int:
    args = parse_args()
    setup_logger(args.camera_id)
    install_exception_logging()

    source = OpenCVVideoSource(args.source)
    session_dirs = SessionDirs.from_root(args.sessions_dir)
    door_reader = RecorderDoorStateReader(
        endpoint=args.zmq_ipc_endpoint,
        door_channel=int(args.door_channel),
        open_value=int(args.door_open_value),
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
