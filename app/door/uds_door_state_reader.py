from __future__ import annotations

import socket
from pathlib import Path


class UdsDoorStateReader:
    """Reads door state from Unix Domain Socket server."""

    def __init__(
        self,
        path: str | Path,
        door_channel: int,
        *,
        timeout_s: float = 0.5,
        initial_state: bool = False,
    ):
        self.path = str(Path(path))
        self.door_channel = int(door_channel)
        self.timeout_s = float(timeout_s)
        self._last_state = bool(initial_state)

    def read(self) -> bool:
        request = f"GET {self.door_channel}\n".encode("ascii")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout_s)
                sock.connect(self.path)
                sock.sendall(request)
                response = self._readline(sock)
        except OSError:
            self._last_state = False
            return self._last_state

        if response == "true":
            self._last_state = True
        elif response == "false":
            self._last_state = False
        else:
            self._last_state = False
        return self._last_state

    @staticmethod
    def _readline(sock: socket.socket) -> str:
        chunks: list[bytes] = []
        while True:
            data = sock.recv(1)
            if not data:
                break
            if data == b"\n":
                break
            chunks.append(data)
        return b"".join(chunks).decode("ascii", errors="ignore").strip().lower()

    def close(self) -> None:
        return None

