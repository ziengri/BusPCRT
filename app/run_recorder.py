from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.door import UdsDoorStateReader, uds_ping
from app.recording import OpenCVVideoSource, SessionRecorderService
from app.shared import SessionDirs
from app.utils import install_exception_logging, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Door-gated recorder process")
    parser.add_argument("--config", default=None, help="Path to JSON config file")
    parser.add_argument("--source", default=None, help="RTSP/file/camera source for cv2.VideoCapture")
    parser.add_argument("--camera-id", dest="camera_id", default=None, help="Camera id")
    parser.add_argument("--sessions-dir", default="sessions", help="Root for active/ready/processing/failed")
    parser.add_argument("--door-sock", default="door.sock", help="Unix Domain Socket path for door daemon")
    parser.add_argument("--door-channel", dest="door_channel", type=int, default=None, help="Door channel from !DOORS packet")
    parser.add_argument("--door-open-value", dest="door_open_value", type=int, default=1, help="Value representing OPEN state")
    parser.add_argument("--serial-port", dest="serial_port", default=None, help="COM port, e.g. COM3")
    parser.add_argument("--serial-baudrate", dest="serial_baudrate", type=int, default=19200)
    parser.add_argument("--serial-parity", dest="serial_parity", default="N")
    parser.add_argument("--serial-stopbits", dest="serial_stopbits", type=float, default=1.0)
    parser.add_argument("--serial-bytesize", dest="serial_bytesize", type=int, default=8)
    parser.add_argument("--serial-timeout", dest="serial_timeout", type=float, default=0.2)
    parser.add_argument("--door-timeout", dest="door_timeout", type=float, default=0.5, help="UDS request timeout in seconds")
    parser.add_argument(
        "--door-daemon-cmd",
        dest="door_daemon_cmd",
        default=None,
        help="Optional command to start door daemon, e.g. 'python app/run_door_daemon.py'",
    )
    parser.add_argument("--door-daemon-ready-timeout", dest="door_daemon_ready_timeout", type=float, default=6.0)
    parser.add_argument("--door-daemon-reconnect", dest="door_daemon_reconnect", type=float, default=0.5)
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
    pre_args, _ = pre_parser.parse_known_args()

    parser = _build_parser()
    if pre_args.config:
        config = _load_config(pre_args.config, parser)
        valid_keys = {action.dest for action in parser._actions}
        unknown = sorted(k for k in config if k not in valid_keys)
        if unknown:
            parser.error(f"Unknown config keys: {', '.join(unknown)}")
        parser.set_defaults(**config)

    args = parser.parse_args()
    if not args.source:
        parser.error("Argument '--source' is required (CLI or config)")
    if not args.camera_id:
        parser.error("Argument '--camera-id' is required (CLI or config)")
    if args.door_channel is None:
        parser.error("Argument '--door-channel' is required")
    if args.serial_stopbits not in (1.0, 1.5, 2.0):
        parser.error("Argument '--serial-stopbits' must be one of: 1, 1.5, 2")
    return args


def _build_door_daemon_command(args: argparse.Namespace) -> list[str]:
    if args.door_daemon_cmd:
        cmd = shlex.split(args.door_daemon_cmd)
    else:
        cmd = [sys.executable, str(Path(__file__).resolve().parent / "run_door_daemon.py")]
    cmd.extend(
        [
            "--door-sock",
            str(args.door_sock),
            "--serial-port",
            str(args.serial_port),
            "--serial-baudrate",
            str(args.serial_baudrate),
            "--serial-parity",
            str(args.serial_parity).upper(),
            "--serial-stopbits",
            str(args.serial_stopbits),
            "--serial-bytesize",
            str(args.serial_bytesize),
            "--serial-timeout",
            str(args.serial_timeout),
            "--door-open-value",
            str(args.door_open_value),
            "--reconnect-interval",
            str(args.door_daemon_reconnect),
            "--log-id",
            f"door-daemon-{args.camera_id}",
        ]
    )
    return cmd


def _spawn_daemon_detached(command: list[str]) -> None:
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def _ensure_door_daemon(args: argparse.Namespace) -> None:
    if uds_ping(args.door_sock, timeout_s=args.door_timeout, channel=args.door_channel):
        return

    if not args.serial_port:
        raise RuntimeError(
            "Door daemon is unavailable and '--serial-port' is not set. "
            "Provide serial settings for recorder auto-start or start daemon manually."
        )

    command = _build_door_daemon_command(args)
    _spawn_daemon_detached(command)

    deadline = time.monotonic() + float(args.door_daemon_ready_timeout)
    while time.monotonic() < deadline:
        if uds_ping(args.door_sock, timeout_s=args.door_timeout, channel=args.door_channel):
            return
        time.sleep(0.2)

    raise RuntimeError(
        f"Door daemon did not become ready on socket '{args.door_sock}' "
        f"for channel {args.door_channel}"
    )


def main() -> int:
    args = parse_args()
    setup_logger(args.camera_id)
    install_exception_logging()

    _ensure_door_daemon(args)

    source = OpenCVVideoSource(args.source)
    session_dirs = SessionDirs.from_root(args.sessions_dir)
    door_reader = UdsDoorStateReader(
        path=args.door_sock,
        door_channel=args.door_channel,
        timeout_s=args.door_timeout,
        initial_state=False,
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
