from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from app.door.uds_door_state_reader import UdsDoorStateReader


pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="Unix Domain Sockets are required",
)


def _serve_once(sock_path: Path, response: str) -> threading.Thread:
    def _worker() -> None:
        if sock_path.exists():
            sock_path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(sock_path))
            server.listen(1)
            conn, _ = server.accept()
            with conn:
                _ = conn.recv(64)
                conn.sendall(response.encode("ascii"))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def test_reader_true_false(tmp_path: Path) -> None:
    sock = tmp_path / "door.sock"

    thread = _serve_once(sock, "true\n")
    reader = UdsDoorStateReader(sock, door_channel=1, timeout_s=0.5)
    assert reader.read() is True
    thread.join(timeout=1.0)

    thread = _serve_once(sock, "false\n")
    assert reader.read() is False
    thread.join(timeout=1.0)


def test_reader_fail_safe_closed_on_error(tmp_path: Path) -> None:
    sock = tmp_path / "missing.sock"
    reader = UdsDoorStateReader(sock, door_channel=1, timeout_s=0.1, initial_state=True)
    assert reader.read() is False

