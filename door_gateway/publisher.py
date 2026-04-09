from __future__ import annotations

import json
import os
from pathlib import Path

import zmq

from .state import Snapshot


def _ipc_path_from_endpoint(endpoint: str) -> Path | None:
    if not endpoint.startswith("ipc://"):
        return None
    return Path(endpoint[len("ipc://") :])


class DoorPublisher:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SNDHWM, 10)

        ipc_path = _ipc_path_from_endpoint(endpoint)
        if ipc_path is not None:
            ipc_path.parent.mkdir(parents=True, exist_ok=True)
            if ipc_path.exists():
                ipc_path.unlink()

        self.socket.bind(endpoint)
        if ipc_path is not None and ipc_path.exists():
            try:
                os.chmod(ipc_path, 0o666)
            except OSError:
                pass

    @staticmethod
    def _to_json(payload: dict) -> str:
        return json.dumps(payload, separators=(",", ":"))

    def _send(self, topic: str, payload: dict) -> None:
        self.socket.send_string(f"{topic} {self._to_json(payload)}", encoding="utf-8")

    def publish_snapshot(self, snap: Snapshot) -> None:
        ts = snap.ts
        seq = snap.seq
        doors_payload = {
            "seq": seq,
            "ts": ts,
            "doors": {"1": snap.doors[1], "2": snap.doors[2], "3": snap.doors[3]},
            "any_open": snap.any_open,
            "all_closed": snap.all_closed,
            "stale": snap.stale,
        }
        self._send("doors.state", doors_payload)

        for door_id in (1, 2, 3):
            self._send(
                f"door.{door_id}.state",
                {
                    "seq": seq,
                    "ts": ts,
                    "door_id": door_id,
                    "state": snap.doors[door_id],
                    "stale": snap.stale,
                },
            )

    def close(self) -> None:
        self.socket.close(0)
