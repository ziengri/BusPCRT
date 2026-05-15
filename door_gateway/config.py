from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.shared import parse_number_cams


@dataclass
class GatewayConfig:
    serial_port: str | None
    serial_port_find: str | None
    door_count: int
    baudrate: int
    bytesize: int
    parity: str
    stopbits: float
    serial_timeout: float
    reconnect_sec: float
    ipc_endpoint: str
    stale_timeout_sec: float
    heartbeat_publish_sec: float
    log_level: str
    log_file: str | None


def _load_env(path_value: str | None) -> dict[str, object]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v not in (None, "")}


def _env_defaults(env_path: str | None, config_env_path: str | None, device_env_path: str | None) -> dict[str, object]:
    raw: dict[str, object] = {}
    raw.update(_load_env(config_env_path))
    raw.update(_load_env(env_path))
    device_raw = _load_env(device_env_path)
    return {
        "serial_port": raw.get("SERIAL_PORT"),
        "serial_port_find": raw.get("SERIAL_PORT_FIND"),
        "door_count": raw.get("DOOR_COUNT") or device_raw.get("NUMBER_CAMS"),
        "baudrate": raw.get("SERIAL_BAUDRATE"),
        "bytesize": raw.get("SERIAL_BYTESIZE"),
        "parity": raw.get("SERIAL_PARITY"),
        "stopbits": raw.get("SERIAL_STOPBITS"),
        "serial_timeout": raw.get("SERIAL_TIMEOUT"),
        "reconnect_sec": raw.get("RECONNECT_SEC"),
        "ipc_endpoint": raw.get("ZMQ_IPC_ENDPOINT"),
        "stale_timeout_sec": raw.get("STALE_TIMEOUT_SEC"),
        "heartbeat_publish_sec": raw.get("HEARTBEAT_PUBLISH_SEC"),
        "log_level": raw.get("LOG_LEVEL"),
        "log_file": raw.get("LOG_FILE"),
    }


def parse_gateway_args() -> GatewayConfig:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config-env-file", default="config.env")
    pre.add_argument("--device-env-file", default="/etc/pcrt/device.env")
    pre.add_argument("--env-file", default="door_gateway.env")
    pre_args, _ = pre.parse_known_args()
    env = _env_defaults(pre_args.env_file, pre_args.config_env_file, pre_args.device_env_file)

    parser = argparse.ArgumentParser(description="door_gateway: RS232 binary -> ZeroMQ PUB")
    parser.add_argument("--config-env-file", default=pre_args.config_env_file)
    parser.add_argument("--device-env-file", default=pre_args.device_env_file)
    parser.add_argument("--env-file", default=pre_args.env_file)
    parser.add_argument("--serial-port", dest="serial_port", default=None)
    parser.add_argument("--serial-port-find", dest="serial_port_find", default=None)
    parser.add_argument("--door-count", dest="door_count", type=int, default=3)
    parser.add_argument("--baudrate", type=int, default=19200)
    parser.add_argument("--bytesize", type=int, default=8)
    parser.add_argument("--parity", default="N")
    parser.add_argument("--stopbits", type=float, default=1.0)
    parser.add_argument("--serial-timeout", dest="serial_timeout", type=float, default=0.2)
    parser.add_argument("--reconnect-sec", dest="reconnect_sec", type=float, default=1.0)
    parser.add_argument("--ipc-endpoint", dest="ipc_endpoint", default="ipc:///run/doors.sock")
    parser.add_argument("--stale-timeout-sec", dest="stale_timeout_sec", type=float, default=2.0)
    parser.add_argument("--heartbeat-publish-sec", dest="heartbeat_publish_sec", type=float, default=0.5)
    parser.add_argument("--log-level", dest="log_level", default="INFO")
    parser.add_argument("--log-file", dest="log_file", default=None)

    parser.set_defaults(**{k: v for k, v in env.items() if v not in (None, "")})
    args = parser.parse_args()
    serial_port = str(args.serial_port).strip() if args.serial_port is not None else None
    serial_port_find = str(args.serial_port_find).strip() if args.serial_port_find is not None else None
    if not serial_port and not serial_port_find:
        parser.error("At least one is required: --serial-port or --serial-port-find (CLI or env)")
    try:
        door_count = parse_number_cams(args.door_count) or 3
    except ValueError as exc:
        parser.error(str(exc).replace("NUMBER_CAMS", "--door-count"))
    return GatewayConfig(
        serial_port=serial_port or None,
        serial_port_find=serial_port_find or None,
        door_count=door_count,
        baudrate=int(args.baudrate),
        bytesize=int(args.bytesize),
        parity=str(args.parity).upper(),
        stopbits=float(args.stopbits),
        serial_timeout=float(args.serial_timeout),
        reconnect_sec=float(args.reconnect_sec),
        ipc_endpoint=str(args.ipc_endpoint),
        stale_timeout_sec=float(args.stale_timeout_sec),
        heartbeat_publish_sec=float(args.heartbeat_publish_sec),
        log_level=str(args.log_level).upper(),
        log_file=str(args.log_file) if args.log_file else None,
    )
