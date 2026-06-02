from __future__ import annotations

import json
from typing import Any

import zmq


class _BaseZmqReader:
    def __init__(self, endpoint: str, topic: str):
        self.endpoint = endpoint
        self.topic = topic
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.RCVHWM, 1)
        self._sock.setsockopt_string(zmq.SUBSCRIBE, topic)
        self._sock.connect(endpoint)

    @staticmethod
    def _split_message(msg: str) -> tuple[str, dict[str, Any] | None]:
        if " " not in msg:
            return "", None
        topic, payload = msg.split(" ", 1)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return topic, None
        if not isinstance(data, dict):
            return topic, None
        return topic, data

    def close(self) -> None:
        self._sock.close(0)


class RecorderDoorStateReader(_BaseZmqReader):
    """Consumes `door.<n>.state` and returns current open/closed state for recorder."""

    def __init__(self, endpoint: str, door_channel: int, open_value: int = 1):
        topic = f"door.{int(door_channel)}.state"
        super().__init__(endpoint=endpoint, topic=topic)
        self.open_value = int(open_value)
        self._current_open = False

    def read(self) -> bool:
        while True:
            try:
                msg = self._sock.recv_string(flags=zmq.NOBLOCK)
            except zmq.Again:
                break
            topic, data = self._split_message(msg)
            if topic != self.topic or data is None:
                continue
            stale = bool(data.get("stale", True))
            if stale:
                self._current_open = False
                continue
            state = int(data.get("state", 0))
            self._current_open = state == self.open_value
        return self._current_open


class ProcessorDoorStateReader(_BaseZmqReader):
    """
    Consumes `doors.state` and returns True when processor must pause.

    Pause condition: all_closed == False.
    """

    def __init__(self, endpoint: str):
        super().__init__(endpoint=endpoint, topic="doors.state")
        self._pause_processing = True

    def read(self) -> bool:
        while True:
            try:
                msg = self._sock.recv_string(flags=zmq.NOBLOCK)
            except zmq.Again:
                break
            topic, data = self._split_message(msg)
            if topic != self.topic or data is None:
                continue
            all_closed = bool(data.get("all_closed", False))
            self._pause_processing = not all_closed
        return self._pause_processing
