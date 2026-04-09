from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.door import DoorDaemon, DoorPacketFileReader


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start RS232 file publisher and print live parsed packets")
    parser.add_argument("--config", default="door_rs232_config.json", help="Path to shared RS232 config")
    parser.add_argument("--door-sock", dest="door_sock", default="door.sock", help="Path to door state file")
    parser.add_argument("--serial-port", dest="serial_port", default=None, help="COM port, e.g. COM3")
    parser.add_argument("--serial-baudrate", dest="serial_baudrate", type=int, default=19200)
    parser.add_argument("--serial-parity", dest="serial_parity", default="N")
    parser.add_argument("--serial-stopbits", dest="serial_stopbits", type=float, default=1.0)
    parser.add_argument("--serial-bytesize", dest="serial_bytesize", type=int, default=8)
    parser.add_argument("--serial-timeout", dest="serial_timeout", type=float, default=0.2)
    parser.add_argument("--reconnect-interval", dest="reconnect_interval", type=float, default=0.5)
    parser.add_argument("--door-open-value", dest="door_open_value", type=int, default=1)
    parser.add_argument("--poll-interval", dest="poll_interval", type=float, default=0.5)
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
    pre_parser.add_argument("--config", default="door_rs232_config.json")
    pre_args, _ = pre_parser.parse_known_args()

    parser = _build_parser()
    if pre_args.config and Path(pre_args.config).exists():
        config = _load_config(pre_args.config, parser)
        valid_keys = {action.dest for action in parser._actions}
        filtered_config = {k: v for k, v in config.items() if k in valid_keys}
        parser.set_defaults(**filtered_config)

    args = parser.parse_args()
    if not args.serial_port:
        parser.error("Argument '--serial-port' is required (CLI or config)")
    return args


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def main() -> int:
    args = parse_args()
    file_reader = DoorPacketFileReader(args.door_sock)

    def _on_packet(raw_packet: str, parsed: dict[int, int]) -> None:
        bool_map = {channel: (value == int(args.door_open_value)) for channel, value in parsed.items()}
        print(f"[{_now_str()}] RS232 raw='{raw_packet}' parsed={parsed} bool={bool_map}")

    daemon = DoorDaemon(
        output_path=args.door_sock,
        serial_port=args.serial_port,
        baudrate=args.serial_baudrate,
        parity=str(args.serial_parity).upper(),
        stopbits=args.serial_stopbits,
        bytesize=args.serial_bytesize,
        timeout=args.serial_timeout,
        reconnect_interval_s=args.reconnect_interval,
        on_packet=_on_packet,
    )

    daemon.start()
    daemon_thread = threading.Thread(target=daemon.serve_forever, daemon=True, name="door-file-publisher")
    daemon_thread.start()
    print(f"[{_now_str()}] Publisher started. Reading '{args.door_sock}'. Press Ctrl+C to stop.")

    last_packet: str | None = None
    try:
        while True:
            packet = file_reader.read_packet()
            if packet and packet != last_packet:
                channels = file_reader.read_channels() or {}
                bool_map = {channel: (value == int(args.door_open_value)) for channel, value in channels.items()}
                print(f"[{_now_str()}] FILE raw='{packet}' parsed={channels} bool={bool_map}")
                last_packet = packet
            time.sleep(float(args.poll_interval))
    except KeyboardInterrupt:
        print(f"[{_now_str()}] Stopped by user")
    finally:
        daemon.stop()
        daemon_thread.join(timeout=1.0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
