from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

import app.door.door_daemon as daemon_module
from app.door.door_daemon import DoorDaemon


pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="Unix Domain Sockets are required",
)


class _FakeSerialReaderThread:
    def __init__(self, state_map, state_lock, **kwargs):
        self._state_map = state_map
        self._state_lock = state_lock

    def start(self) -> None:
        with self._state_lock:
            self._state_map[1] = True
            self._state_map[2] = False

    def stop(self) -> None:
        return None


def _request(sock_path: Path, payload: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(sock_path))
        client.sendall(payload.encode("ascii"))
        data = b""
        while not data.endswith(b"\n"):
            part = client.recv(1)
            if not part:
                break
            data += part
    return data.decode("ascii", errors="ignore").strip()


def test_door_daemon_get_and_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(daemon_module, "SerialReaderThread", _FakeSerialReaderThread)
    sock = tmp_path / "door.sock"

    daemon = DoorDaemon(
        socket_path=sock,
        serial_port="COM1",
    )
    daemon.start()
    server_thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    server_thread.start()

    try:
        assert _request(sock, "GET 1\n") == "true"
        assert _request(sock, "GET 2\n") == "false"
        assert _request(sock, "GET 999\n") == "false"
        assert _request(sock, "BAD\n").startswith("ERR")
    finally:
        daemon.stop()
        server_thread.join(timeout=1.0)

