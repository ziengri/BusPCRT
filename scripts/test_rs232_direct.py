from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import serial  # type: ignore[import-untyped]
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from door_gateway.protocol import parse_packet
from door_gateway.serial_reader import extract_packets
from app.shared import parse_number_cams


def parse_args() -> argparse.Namespace:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", default="door_gateway.env")
    pre.add_argument("--device-env-file", default="/etc/pcrt/device.env")
    pre_args, _ = pre.parse_known_args()

    env = {}
    env_path = Path(pre_args.env_file)
    if env_path.exists():
        env = dotenv_values(env_path)
    device_env = {}
    device_env_path = Path(pre_args.device_env_file)
    if device_env_path.exists():
        device_env = dotenv_values(device_env_path)

    door_count_default = env.get("DOOR_COUNT") or device_env.get("NUMBER_CAMS") or "3"

    parser = argparse.ArgumentParser(description="Direct RS232 binary debug reader")
    parser.add_argument("--env-file", default=pre_args.env_file)
    parser.add_argument("--device-env-file", default=pre_args.device_env_file)
    parser.add_argument("--serial-port", default=env.get("SERIAL_PORT"))
    parser.add_argument("--door-count", type=int, default=int(str(door_count_default)))
    parser.add_argument("--baudrate", type=int, default=int(env.get("SERIAL_BAUDRATE", "19200")))
    parser.add_argument("--bytesize", type=int, default=int(env.get("SERIAL_BYTESIZE", "8")))
    parser.add_argument("--parity", default=str(env.get("SERIAL_PARITY", "N")))
    parser.add_argument("--stopbits", type=float, default=float(env.get("SERIAL_STOPBITS", "1.0")))
    parser.add_argument("--serial-timeout", type=float, default=float(env.get("SERIAL_TIMEOUT", "0.2")))
    parser.add_argument("--reconnect-sec", type=float, default=float(env.get("RECONNECT_SEC", "1.0")))
    args = parser.parse_args()
    if not args.serial_port:
        parser.error("--serial-port is required")
    try:
        args.door_count = parse_number_cams(args.door_count) or 3
    except ValueError:
        parser.error("--door-count must be 3 or 4")
    return args


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _doors_repr(doors: dict[int, object]) -> str:
    return ", ".join(
        f"door={door_id} state=\\x{getattr(item, 'state'):02x} voltage={int(getattr(item, 'voltage'))}V"
        for door_id, item in sorted(doors.items())
    )


def main() -> int:
    args = parse_args()
    buffer = bytearray()

    while True:
        try:
            ser = serial.Serial(
                port=args.serial_port,
                baudrate=args.baudrate,
                bytesize=args.bytesize,
                parity=args.parity.upper(),
                stopbits=args.stopbits,
                timeout=args.serial_timeout,
            )
            print(f"Connected: {args.serial_port}")
        except Exception as exc:  # noqa: BLE001
            print(f"Open error: {exc}")
            time.sleep(args.reconnect_sec)
            continue

        with ser:
            try:
                while True:
                    chunk = ser.read(64)
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    packets = extract_packets(buffer, door_count=args.door_count)
                    for packet in packets:
                        try:
                            doors = parse_packet(packet, door_count=args.door_count)
                            print(f"VALID hex={_hex(packet)} doors={_doors_repr(doors)}")
                        except ValueError as exc:
                            print(f"INVALID hex={_hex(packet)} err={exc}")
            except KeyboardInterrupt:
                return 0
            except Exception as exc:  # noqa: BLE001
                print(f"Read error: {exc}")
                time.sleep(args.reconnect_sec)


if __name__ == "__main__":
    raise SystemExit(main())
