from __future__ import annotations

import glob
import logging
import time

import serial

from .config import GatewayConfig, parse_gateway_args
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


def _open_serial(cfg: GatewayConfig, port: str) -> serial.Serial:
    return serial.Serial(
        port=port,
        baudrate=cfg.baudrate,
        bytesize=cfg.bytesize,
        parity=cfg.parity,
        stopbits=cfg.stopbits,
        timeout=cfg.serial_timeout,
    )


def _probe_port_for_protocol(
    ser: serial.Serial,
    probe_timeout_sec: float = 1.5,
) -> tuple[bool, dict[int, int] | None]:
    buffer = bytearray()
    deadline = time.time() + probe_timeout_sec
    while time.time() < deadline:
        chunk = ser.read(64)
        if not chunk:
            continue
        buffer.extend(chunk)
        packets = extract_packets(buffer)
        for packet in packets:
            try:
                doors = parse_packet(packet)
            except ValueError:
                continue
            return True, doors
    return False, None


def _select_serial_port(cfg: GatewayConfig, logger: logging.Logger) -> tuple[serial.Serial, str, dict[int, int] | None] | None:
    if cfg.serial_port:
        try:
            ser = _open_serial(cfg, cfg.serial_port)
            logger.info("Serial opened on fixed port: %s", cfg.serial_port)
            return ser, cfg.serial_port, None
        except Exception as exc:  # noqa: BLE001
            logger.error("Fixed serial open failed (%s): %s", cfg.serial_port, exc)

    if not cfg.serial_port_find:
        return None

    candidates = sorted(glob.glob(cfg.serial_port_find))
    if not candidates:
        logger.warning("No serial ports matched pattern: %s", cfg.serial_port_find)
        return None
    logger.info("Scanning serial ports by pattern '%s': %s", cfg.serial_port_find, ", ".join(candidates))

    for port in candidates:
        try:
            ser = _open_serial(cfg, port)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Candidate open failed (%s): %s", port, exc)
            continue

        try:
            ok, doors = _probe_port_for_protocol(ser)
            if ok:
                logger.info("Serial probe matched door protocol on port: %s", port)
                return ser, port, doors
            logger.warning("Serial probe failed on port (no valid packet): %s", port)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Serial probe error on port (%s): %s", port, exc)
        finally:
            if ser.is_open:
                ser.close()

    logger.warning("No working serial port found for pattern: %s", cfg.serial_port_find)
    return None


def main() -> int:
    cfg = parse_gateway_args()
    _setup_logging(cfg.log_level, cfg.log_file)
    logger = logging.getLogger("door_gateway")
    logger.info(
        "Starting door_gateway with endpoint=%s serial=%s serial_find=%s",
        cfg.ipc_endpoint,
        cfg.serial_port,
        cfg.serial_port_find,
    )

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

        selected = _select_serial_port(cfg, logger)
        if selected is None:
            logger.warning("Serial selection failed, retrying in %.2fs", cfg.reconnect_sec)
            time.sleep(cfg.reconnect_sec)
            continue
        ser, active_port, probe_doors = selected
        buffer.clear()

        if probe_doors is not None:
            ts = time.time()
            snap = store.update_from_doors(probe_doors, ts)
            publisher.publish_snapshot(snap)
            last_heartbeat_ts = ts
            if stale_logged:
                logger.info("Door state recovered from stale")
                stale_logged = False

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
                    chunk = ser.read(64)

                except Exception as exc:  # noqa: BLE001
                    logger.error("Serial read error (%s): %s", active_port, exc)
                    break

                if not chunk:
                    continue

                buffer.extend(chunk)
                packets = extract_packets(buffer)
                for packet in packets:
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

        logger.warning("Serial disconnected (%s), reconnecting in %.2fs", active_port, cfg.reconnect_sec)
        time.sleep(cfg.reconnect_sec)


if __name__ == "__main__":
    raise SystemExit(main())
