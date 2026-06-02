from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

import zmq

from .protocol import configured_door_ids
from .state import Snapshot


def _ipc_path_from_endpoint(endpoint: str) -> Path | None:
    if not endpoint.startswith("ipc://"):
        return None
    return Path(endpoint[len("ipc://") :])


class DoorPublisher:
    def __init__(self, endpoint: str, *, door_count: int = 3, door_ids: Iterable[int] | None = None):
        self.endpoint = endpoint
        self.door_ids = tuple(door_ids) if door_ids is not None else configured_door_ids(door_count)
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
            "doors": {
                str(door_id): {
                    "state": snap.doors[door_id].state,
                    "voltage": snap.doors[door_id].voltage,
                }
                for door_id in self.door_ids
            },
            "any_open": snap.any_open,
            "all_closed": snap.all_closed,
            "stale": snap.stale,
        }
        self._send("doors.state", doors_payload)

        for door_id in self.door_ids:
            self._send(
                f"door.{door_id}.state",
                {
                    "seq": seq,
                    "ts": ts,
                    "door_id": door_id,
                    "state": snap.doors[door_id].state,
                    "voltage": snap.doors[door_id].voltage,
                    "stale": snap.stale,
                },
            )

    def close(self) -> None:
        self.socket.close(0)
