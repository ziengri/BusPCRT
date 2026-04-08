from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.door.doors_protocol_parser import DoorsProtocolParser

try:
    import serial  # type: ignore[import-untyped]
except ModuleNotFoundError:
    serial = None  # type: ignore[assignment]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RS232 door protocol debug reader")
    parser.add_argument("--config", default=None, help="Path to JSON config file")
    parser.add_argument("--serial-port", dest="serial_port", default=None, help="RS232 port, e.g. COM3")
    parser.add_argument("--serial-baudrate", dest="serial_baudrate", type=int, default=19200)
    parser.add_argument("--serial-parity", dest="serial_parity", default="N")
    parser.add_argument("--serial-stopbits", dest="serial_stopbits", type=float, default=1.0)
    parser.add_argument("--serial-bytesize", dest="serial_bytesize", type=int, default=8)
    parser.add_argument("--serial-timeout", dest="serial_timeout", type=float, default=0.2)
    parser.add_argument("--reconnect-interval", dest="reconnect_interval", type=float, default=0.5)
    parser.add_argument("--door-channel", dest="door_channel", type=int, default=None, help="Optional channel to highlight")
    parser.add_argument("--door-open-value", "--open-value", dest="open_value", type=int, default=1, help="Value interpreted as OPEN")
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


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main() -> int:
    args = parse_args()
    if serial is None:
        raise RuntimeError("pyserial is not installed; install 'pyserial' first")

    parser = DoorsProtocolParser()
    port = None
    next_reconnect_ts = 0.0

    print("Starting RS232 protocol debug reader. Press Ctrl+C to stop.")

    try:
        while True:
            if port is None or not getattr(port, "is_open", False):
                now = time.monotonic()
                if now < next_reconnect_ts:
                    time.sleep(0.05)
                    continue
                try:
                    port = serial.Serial(
                        port=args.serial_port,
                        baudrate=args.serial_baudrate,
                        parity=str(args.serial_parity).upper(),
                        stopbits=args.serial_stopbits,
                        bytesize=args.serial_bytesize,
                        timeout=args.serial_timeout,
                    )
                    print(f"[{_now_str()}] Connected to {args.serial_port}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[{_now_str()}] Connect error: {exc}")
                    next_reconnect_ts = now + float(args.reconnect_interval)
                    continue

            try:
                raw = port.readline()
            except Exception as exc:  # noqa: BLE001
                print(f"[{_now_str()}] Read error: {exc}")
                try:
                    port.close()
                except Exception:  # noqa: BLE001
                    pass
                port = None
                next_reconnect_ts = time.monotonic() + float(args.reconnect_interval)
                continue

            if not raw:
                continue

            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                continue

            try:
                parsed = parser.parse(line)
                bool_map = {k: (v == int(args.open_value)) for k, v in parsed.items()}
                if args.door_channel is not None:
                    selected = bool_map.get(int(args.door_channel), False)
                    print(
                        f"[{_now_str()}] raw='{line}' parsed={parsed} "
                        f"door_state={bool_map} channel_{args.door_channel}={selected}"
                    )
                else:
                    print(f"[{_now_str()}] raw='{line}' parsed={parsed} door_state={bool_map}")
            except ValueError as exc:
                print(f"[{_now_str()}] raw='{line}' parse_error={exc}")
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        if port is not None:
            try:
                port.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    raise SystemExit(main())
