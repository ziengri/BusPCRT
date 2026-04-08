from __future__ import annotations

from types import SimpleNamespace

import app.door.serial_door_state_reader as serial_reader_module
from app.door.serial_door_state_reader import SerialDoorStateReader


class _FakeSerialException(Exception):
    pass


class _FakePort:
    def __init__(self, items):
        self._items = list(items)
        self.is_open = True

    def readline(self) -> bytes:
        if not self._items:
            return b""
        value = self._items.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self) -> None:
        self.is_open = False


def test_serial_reader_open_close_and_invalid_keeps_last(monkeypatch) -> None:
    fake_port = _FakePort(
        [
            b"!DOORS;1=1;2=0;3=1\r\n",
            b"!DOORS;1=0;2=0;3=1\n",
            b"bad packet\n",
        ]
    )
    fake_serial = SimpleNamespace(
        SerialException=_FakeSerialException,
        Serial=lambda **_: fake_port,
    )
    monkeypatch.setattr(serial_reader_module, "serial", fake_serial)

    reader = SerialDoorStateReader(
        port="COM1",
        door_channel=1,
        open_value=1,
        reconnect_interval_s=0.0,
        initial_state=False,
    )
    assert reader.read() is True
    assert reader.read() is False
    assert reader.read() is False


def test_serial_reader_reconnect(monkeypatch) -> None:
    calls = {"n": 0}
    fake_port = _FakePort([b"!DOORS;1=1\r\n"])

    def _serial_factory(**_):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _FakeSerialException("port unavailable")
        return fake_port

    fake_serial = SimpleNamespace(
        SerialException=_FakeSerialException,
        Serial=_serial_factory,
    )
    monkeypatch.setattr(serial_reader_module, "serial", fake_serial)

    reader = SerialDoorStateReader(
        port="COM2",
        door_channel=1,
        open_value=1,
        reconnect_interval_s=0.0,
        initial_state=False,
    )
    assert reader.read() is False
    assert reader.read() is True

