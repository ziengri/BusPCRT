from __future__ import annotations

import time
from typing import Any

from .doors_protocol_parser import DoorsProtocolParser

try:
    import serial  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - tested via runtime behavior
    serial = None  # type: ignore[assignment]


class SerialDoorStateReader:
    """Reads door state from RS232 stream using !DOORS protocol messages."""

    def __init__(
        self,
        port: str,
        door_channel: int,
        open_value: int = 1,
        *,
        baudrate: int = 19200,
        parity: str = "N",
        stopbits: float = 1.0,
        bytesize: int = 8,
        timeout: float = 0.2,
        reconnect_interval_s: float = 0.5,
        initial_state: bool = False,
        parser: DoorsProtocolParser | None = None,
    ):
        if not port:
            raise ValueError("Serial port must be non-empty")

        self.port = port
        self.door_channel = int(door_channel)
        self.open_value = int(open_value)
        self.baudrate = int(baudrate)
        self.parity = parity
        self.stopbits = stopbits
        self.bytesize = int(bytesize)
        self.timeout = float(timeout)
        self.reconnect_interval_s = float(reconnect_interval_s)

        self._parser = parser or DoorsProtocolParser()
        self._last_state = bool(initial_state)
        self._serial: Any | None = None
        self._next_reconnect_ts = 0.0

    def _serial_exception_types(self) -> tuple[type[BaseException], ...]:
        if serial is None:
            return (OSError,)
        serial_exc = getattr(serial, "SerialException", OSError)
        return (serial_exc, OSError)

    def _open_serial(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed; install 'pyserial' for RS232 support")

        self._serial = serial.Serial(
            port=self.port,
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
        if self._serial is None:
            return
        try:
            self._serial.close()
        except Exception:  # noqa: BLE001
            pass
        self._serial = None
        self._next_reconnect_ts = time.monotonic() + self.reconnect_interval_s

    def read(self) -> bool:
        if not self._ensure_connected():
            return self._last_state

        try:
            raw_bytes = self._serial.readline()
        except self._serial_exception_types():
            self._disconnect()
            return self._last_state

        if not raw_bytes:
            return self._last_state

        line = raw_bytes.decode("ascii", errors="ignore").strip()
        if not line:
            return self._last_state

        try:
            values = self._parser.parse(line)
        except ValueError:
            return self._last_state

        if self.door_channel in values:
            self._last_state = values[self.door_channel] == self.open_value
        return self._last_state

    def close(self) -> None:
        self._disconnect()

