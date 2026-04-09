from __future__ import annotations

import argparse
import time
from pathlib import Path

import serial  # type: ignore[import-untyped]
from dotenv import dotenv_values

from door_gateway.protocol import parse_packet
from door_gateway.serial_reader import extract_packets


def parse_args() -> argparse.Namespace:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--env-file", default="door_gateway.env")
    pre_args, _ = pre.parse_known_args()

    env = {}
    env_path = Path(pre_args.env_file)
    if env_path.exists():
        env = dotenv_values(env_path)

    parser = argparse.ArgumentParser(description="Direct RS232 binary debug reader")
    parser.add_argument("--env-file", default=pre_args.env_file)
    parser.add_argument("--serial-port", default=env.get("SERIAL_PORT"))
    parser.add_argument("--baudrate", type=int, default=int(env.get("SERIAL_BAUDRATE", "19200")))
    parser.add_argument("--bytesize", type=int, default=int(env.get("SERIAL_BYTESIZE", "8")))
    parser.add_argument("--parity", default=str(env.get("SERIAL_PARITY", "N")))
    parser.add_argument("--stopbits", type=float, default=float(env.get("SERIAL_STOPBITS", "1.0")))
    parser.add_argument("--serial-timeout", type=float, default=float(env.get("SERIAL_TIMEOUT", "0.2")))
    parser.add_argument("--reconnect-sec", type=float, default=float(env.get("RECONNECT_SEC", "1.0")))
    args = parser.parse_args()
    if not args.serial_port:
        parser.error("--serial-port is required")
    return args


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


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
                    packets = extract_packets(buffer)
                    for packet in packets:
                        try:
                            doors = parse_packet(packet)
                            print(f"VALID hex={_hex(packet)} doors={doors}")
                        except ValueError as exc:
                            print(f"INVALID hex={_hex(packet)} err={exc}")
            except KeyboardInterrupt:
                return 0
            except Exception as exc:  # noqa: BLE001
                print(f"Read error: {exc}")
                time.sleep(args.reconnect_sec)


if __name__ == "__main__":
    raise SystemExit(main())
