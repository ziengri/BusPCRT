from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .doors_protocol_parser import DoorsProtocolParser

try:
    import serial  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    serial = None  # type: ignore[assignment]


class SerialDoorPublisherThread(threading.Thread):
    """Reads RS232 packets and writes last valid raw packet to door.sock file."""

    def __init__(
        self,
        *,
        output_path: str | Path,
        serial_port: str,
        baudrate: int = 19200,
        parity: str = "N",
        stopbits: float = 1.0,
        bytesize: int = 8,
        timeout: float = 0.2,
        reconnect_interval_s: float = 0.5,
        parser: DoorsProtocolParser | None = None,
        on_packet: Callable[[str, dict[int, int]], None] | None = None,
    ) -> None:
        super().__init__(name="door-rs232-publisher", daemon=True)
        self.output_path = Path(output_path)
        self.serial_port = serial_port
        self.baudrate = int(baudrate)
        self.parity = str(parity).upper()
        self.stopbits = float(stopbits)
        self.bytesize = int(bytesize)
        self.timeout = float(timeout)
        self.reconnect_interval_s = float(reconnect_interval_s)

        self._parser = parser or DoorsProtocolParser()
        self._on_packet = on_packet
        self._serial: Any | None = None
        self._next_reconnect_ts = 0.0
        self._stop_event = threading.Event()

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def _serial_exception_types(self) -> tuple[type[BaseException], ...]:
        if serial is None:
            return (OSError,)
        serial_exc = getattr(serial, "SerialException", OSError)
        return (serial_exc, OSError)

    def _open_serial(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed; install 'pyserial' for RS232 support")
        self._serial = serial.Serial(
            port=self.serial_port,
            baudrate=self.baudrate,
            parity=self.parity,
            stopbits=self.stopbits,
            bytesize=self.bytesize,
            timeout=self.timeout,
        )

    def _ensure_connected(self) -> bool:
        if self._serial is not None and getattr(self._serial, "is_open", False):
            return True

        now = time.monotonic()
        if now < self._next_reconnect_ts:
            return False

        try:
            self._open_serial()
            return True
        except self._serial_exception_types():
            self._serial = None
            self._next_reconnect_ts = now + self.reconnect_interval_s
            return False

    def _disconnect(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
        self._serial = None
        self._next_reconnect_ts = time.monotonic() + self.reconnect_interval_s

    def _write_packet(self, packet: str) -> None:
        tmp_path = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
        tmp_path.write_text(packet, encoding="ascii")
        os.replace(tmp_path, self.output_path)

    def stop(self) -> None:
        self._stop_event.set()
        self._disconnect()

    def run(self) -> None:
        while not self._stop_event.is_set():
            if not self._ensure_connected():
                time.sleep(0.05)
                continue

            try:
                raw_bytes = self._serial.readline()
            except self._serial_exception_types():
                self._disconnect()
                continue

            if not raw_bytes:
                continue

            line = raw_bytes.decode("ascii", errors="ignore").strip()
            if not line:
                continue

            try:
                parsed = self._parser.parse(line)
            except ValueError:
                continue

            # Preserve packet wire shape expected by readers.
            packet = line if line.endswith(";") else f"{line};"
            self._write_packet(packet)
            if self._on_packet is not None:
                try:
                    self._on_packet(packet, parsed)
                except Exception:  # noqa: BLE001
                    pass


class DoorDaemon:
    """Compatibility wrapper: starts/stops RS232 file publisher thread."""

    def __init__(
        self,
        *,
        output_path: str | Path,
        serial_port: str,
        baudrate: int = 19200,
        parity: str = "N",
        stopbits: float = 1.0,
        bytesize: int = 8,
        timeout: float = 0.2,
        reconnect_interval_s: float = 0.5,
        on_packet: Callable[[str, dict[int, int]], None] | None = None,
    ) -> None:
        self._stop_event = threading.Event()
        self._publisher = SerialDoorPublisherThread(
            output_path=output_path,
            serial_port=serial_port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
            reconnect_interval_s=reconnect_interval_s,
            on_packet=on_packet,
        )

    def start(self) -> None:
        if not self._publisher.is_alive():
            self._publisher.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._publisher.stop()
        if self._publisher.is_alive():
            self._publisher.join(timeout=1.0)

    def serve_forever(self) -> None:
        self.start()
        try:
            while not self._stop_event.is_set():
                time.sleep(0.2)
        finally:
            self.stop()
