from __future__ import annotations

import logging
import time

import serial

from .config import parse_gateway_args
from .protocol import parse_packet
from .publisher import DoorPublisher
from .serial_reader import extract_packets
from .state import DoorStateStore


def _setup_logging(level: str, log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def _packet_hex(packet: bytes) -> str:
    return " ".join(f"{b:02X}" for b in packet)


def main() -> int:
    cfg = parse_gateway_args()
    _setup_logging(cfg.log_level, cfg.log_file)
    logger = logging.getLogger("door_gateway")
    logger.info("Starting door_gateway with endpoint=%s serial=%s", cfg.ipc_endpoint, cfg.serial_port)

    try:
        publisher = DoorPublisher(cfg.ipc_endpoint)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to bind ZeroMQ PUB endpoint %s: %s", cfg.ipc_endpoint, exc)
        return 2

    logger.info("ZeroMQ PUB bound on %s", cfg.ipc_endpoint)

    store = DoorStateStore()
    publisher.publish_snapshot(store.snapshot(time.time()))
    last_heartbeat_ts = time.time()
    stale_logged = True

    buffer = bytearray()
    while True:
        now = time.time()
        if store.mark_stale_if_needed(now, cfg.stale_timeout_sec):
            snap = store.snapshot(now)
            publisher.publish_snapshot(snap)
            logger.warning("Door state became stale")
            stale_logged = True

        if now - last_heartbeat_ts >= cfg.heartbeat_publish_sec:
            publisher.publish_snapshot(store.snapshot(now))
            last_heartbeat_ts = now

        try:
            ser = serial.Serial(
                port=cfg.serial_port,
                baudrate=cfg.baudrate,
                bytesize=cfg.bytesize,
                parity=cfg.parity,
                stopbits=cfg.stopbits,
                timeout=cfg.serial_timeout,
            )
            logger.info("Serial opened: %s", cfg.serial_port)
        except Exception as exc:  # noqa: BLE001
            logger.error("Serial open failed (%s): %s", cfg.serial_port, exc)
            time.sleep(cfg.reconnect_sec)
            continue

        with ser:
            while True:
                now = time.time()
                if store.mark_stale_if_needed(now, cfg.stale_timeout_sec):
                    snap = store.snapshot(now)
                    publisher.publish_snapshot(snap)
                    logger.warning("Door state became stale")
                    stale_logged = True

                if now - last_heartbeat_ts >= cfg.heartbeat_publish_sec:
                    publisher.publish_snapshot(store.snapshot(now))
                    last_heartbeat_ts = now

                try:
                    chunk = ser.read(cfg.bytesize)

                except Exception as exc:  # noqa: BLE001
                    logger.error("Serial read error: %s", exc)
                    break

                if not chunk:
                    continue

                buffer.extend(chunk)
                packets = extract_packets(buffer)
                for packet in packets:
                    packet += b'\x3b'
                    try:
                        doors = parse_packet(packet)
                    except ValueError as exc:
                        logger.warning("Invalid packet (%s): %s", _packet_hex(packet), exc)
                        continue

                    ts = time.time()
                    snap = store.update_from_doors(doors, ts)
                    publisher.publish_snapshot(snap)
                    logger.debug("Valid packet hex=%s doors=%s", _packet_hex(packet), doors)
                    last_heartbeat_ts = ts
                    if stale_logged:
                        logger.info("Door state recovered from stale")
                        stale_logged = False

        logger.warning("Serial disconnected, reconnecting in %.2fs", cfg.reconnect_sec)
        time.sleep(cfg.reconnect_sec)


if __name__ == "__main__":
    raise SystemExit(main())
