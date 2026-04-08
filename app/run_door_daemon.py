from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.door.door_daemon import DoorDaemon
from app.utils import install_exception_logging, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RS232 -> UDS door daemon")
    parser.add_argument("--config", default=None, help="Path to JSON config file")
    parser.add_argument("--door-sock", dest="door_sock", default="door.sock", help="Unix domain socket path (.sock)")
    parser.add_argument("--serial-port", dest="serial_port", default=None, help="RS232 port path/device")
    parser.add_argument("--serial-baudrate", type=int, default=19200)
    parser.add_argument("--serial-parity", default="N")
    parser.add_argument("--serial-stopbits", type=float, default=1.0)
    parser.add_argument("--serial-bytesize", type=int, default=8)
    parser.add_argument("--serial-timeout", type=float, default=0.2)
    parser.add_argument("--door-open-value", dest="door_open_value", type=int, default=1)
    parser.add_argument("--door-channel", dest="door_channel", type=int, default=None, help="Accepted for shared config compatibility")
    parser.add_argument("--reconnect-interval", dest="reconnect_interval", type=float, default=0.5)
    parser.add_argument("--log-id", dest="log_id", default="door-daemon")
    return parser


def _load_config(path: str, parser: argparse.ArgumentParser) -> dict[str, object]:
    cfg_path = Path(path)
    try:
        payload = json.loads(cfg_path.read_text(encoding="utf-8"))
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
    if not args.serial_port:
        parser.error("Argument '--serial-port' is required (CLI or config)")
    if args.serial_stopbits not in (1.0, 1.5, 2.0):
        parser.error("Argument '--serial-stopbits' must be one of: 1, 1.5, 2")
    return args


def main() -> int:
    args = parse_args()
    setup_logger(args.log_id)
    install_exception_logging()

    daemon = DoorDaemon(
        socket_path=args.door_sock,
        serial_port=args.serial_port,
        open_value=args.door_open_value,
        baudrate=args.serial_baudrate,
        parity=str(args.serial_parity).upper(),
        stopbits=args.serial_stopbits,
        bytesize=args.serial_bytesize,
        timeout=args.serial_timeout,
        reconnect_interval_s=args.reconnect_interval,
    )
    daemon.start()
    daemon.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
