from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.run_recorder as run_recorder


def test_ensure_door_daemon_autostart_success(monkeypatch) -> None:
    calls = {"spawned": False}
    ping_sequence = iter([False, False, True])

    monkeypatch.setattr(run_recorder, "uds_ping", lambda *a, **k: next(ping_sequence))
    monkeypatch.setattr(run_recorder, "_spawn_daemon_detached", lambda cmd: calls.update({"spawned": True}))
    monkeypatch.setattr(run_recorder.time, "sleep", lambda _: None)

    args = SimpleNamespace(
        door_sock="/tmp/door.sock",
        door_timeout=0.1,
        door_channel=2,
        serial_port="/dev/ttyS0",
        serial_baudrate=19200,
        serial_parity="N",
        serial_stopbits=1.0,
        serial_bytesize=8,
        serial_timeout=0.2,
        door_open_value=1,
        door_daemon_reconnect=0.5,
        door_daemon_cmd=None,
        door_daemon_ready_timeout=1.0,
        camera_id="cam1",
    )

    run_recorder._ensure_door_daemon(args)
    assert calls["spawned"] is True


def test_ensure_door_daemon_timeout(monkeypatch) -> None:
    monkeypatch.setattr(run_recorder, "uds_ping", lambda *a, **k: False)
    monkeypatch.setattr(run_recorder, "_spawn_daemon_detached", lambda cmd: None)
    monkeypatch.setattr(run_recorder.time, "sleep", lambda _: None)

    args = SimpleNamespace(
        door_sock="/tmp/door.sock",
        door_timeout=0.1,
        door_channel=2,
        serial_port="/dev/ttyS0",
        serial_baudrate=19200,
        serial_parity="N",
        serial_stopbits=1.0,
        serial_bytesize=8,
        serial_timeout=0.2,
        door_open_value=1,
        door_daemon_reconnect=0.5,
        door_daemon_cmd=None,
        door_daemon_ready_timeout=0.0,
        camera_id="cam1",
    )

    with pytest.raises(RuntimeError):
        run_recorder._ensure_door_daemon(args)

