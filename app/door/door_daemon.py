from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any

from .doors_protocol_parser import DoorsProtocolParser

try:
    import serial  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    serial = None  # type: ignore[assignment]


class SerialReaderThread(threading.Thread):
    """Reads RS232 and updates shared door state map."""

    def __init__(
        self,
        state_map: dict[int, bool],
        state_lock: threading.Lock,
        *,
        port: str,
        open_value: int = 1,
        baudrate: int = 19200,
        parity: str = "N",
        stopbits: float = 1.0,
        bytesize: int = 8,
        timeout: float = 0.2,
        reconnect_interval_s: float = 0.5,
        parser: DoorsProtocolParser | None = None,
        stop_event: threading.Event | None = None,
    ):
        super().__init__(name="door-serial-reader", daemon=True)
        self._state_map = state_map
        self._state_lock = state_lock
        self._stop_event = stop_event or threading.Event()

        self.port = port
        self.open_value = int(open_value)
        self.baudrate = int(baudrate)
        self.parity = parity
        self.stopbits = stopbits
        self.bytesize = int(bytesize)
        self.timeout = float(timeout)
        self.reconnect_interval_s = float(reconnect_interval_s)

        self._parser = parser or DoorsProtocolParser()
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
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
        self._serial = None
        self._next_reconnect_ts = time.monotonic() + self.reconnect_interval_s

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

            with self._state_lock:
                for channel, value in parsed.items():
                    self._state_map[channel] = value == self.open_value


class DoorDaemon:
    """Door daemon serving current door state via Unix Domain Socket."""

    def __init__(
        self,
        *,
        socket_path: str | Path,
        serial_port: str,
        open_value: int = 1,
        baudrate: int = 19200,
        parity: str = "N",
        stopbits: float = 1.0,
        bytesize: int = 8,
        timeout: float = 0.2,
        reconnect_interval_s: float = 0.5,
    ):
        self.socket_path = Path(socket_path)
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._state_map: dict[int, bool] = {}
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server: socket.socket | None = None
        self._serial_thread = SerialReaderThread(
            self._state_map,
            self._state_lock,
            port=serial_port,
            open_value=open_value,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            bytesize=bytesize,
            timeout=timeout,
            reconnect_interval_s=reconnect_interval_s,
            stop_event=self._stop_event,
        )

    def start(self) -> None:
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError as exc:
                raise RuntimeError(f"Failed to remove stale socket {self.socket_path}: {exc}") from exc

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.socket_path))
        self._server.listen(16)
        self._server.settimeout(0.5)
        self._serial_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._serial_thread.stop()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass

    def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("DoorDaemon is not started")
        try:
            while not self._stop_event.is_set():
                try:
                    conn, _ = self._server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    continue
                with conn:
                    self._handle_connection(conn)
        finally:
            self.stop()

    def _handle_connection(self, conn: socket.socket) -> None:
        request = self._readline(conn)
        if not request:
            self._send(conn, "ERR empty request\n")
            return

        parts = request.split()
        if len(parts) != 2 or parts[0] != "GET":
            self._send(conn, "ERR bad request\n")
            return

        try:
            channel = int(parts[1])
        except ValueError:
            self._send(conn, "ERR invalid channel\n")
            return

        with self._state_lock:
            state = self._state_map.get(channel, False)
        self._send(conn, "true\n" if state else "false\n")

    @staticmethod
    def _readline(conn: socket.socket) -> str:
        chunks: list[bytes] = []
        while True:
            data = conn.recv(1)
            if not data:
                break
            if data == b"\n":
                break
            chunks.append(data)
        return b"".join(chunks).decode("ascii", errors="ignore").strip()

    @staticmethod
    def _send(conn: socket.socket, payload: str) -> None:
        conn.sendall(payload.encode("ascii"))


def uds_ping(socket_path: str | Path, *, timeout_s: float = 0.3, channel: int = 1) -> bool:
    """Returns True if door daemon responds with true/false to GET request."""
    request = f"GET {int(channel)}\n".encode("ascii")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_s)
            sock.connect(str(socket_path))
            sock.sendall(request)
            data = b""
            while not data.endswith(b"\n"):
                part = sock.recv(1)
                if not part:
                    break
                data += part
    except OSError:
        return False

    response = data.decode("ascii", errors="ignore").strip().lower()
    return response in {"true", "false"}
