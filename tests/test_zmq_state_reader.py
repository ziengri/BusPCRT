from __future__ import annotations

from app.door.zmq_state_reader import ProcessorDoorStateReader


class _FakeSocket:
    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)

    def recv_string(self, flags=None) -> str:
        import zmq

        if not self._messages:
            raise zmq.Again()
        return self._messages.pop(0)

    def close(self, linger: int) -> None:
        return None


def test_processor_ignores_stale_when_all_doors_closed() -> None:
    reader = ProcessorDoorStateReader(endpoint="inproc://test")
    reader._sock.close(0)
    reader._sock = _FakeSocket(
        [
            'doors.state {"stale": true, "all_closed": true}',
        ]
    )

    try:
        assert reader.read() is False
    finally:
        reader.close()


def test_processor_pauses_when_any_door_open_even_if_not_stale() -> None:
    reader = ProcessorDoorStateReader(endpoint="inproc://test")
    reader._sock.close(0)
    reader._sock = _FakeSocket(
        [
            'doors.state {"stale": false, "all_closed": false}',
        ]
    )

    try:
        assert reader.read() is True
    finally:
        reader.close()
