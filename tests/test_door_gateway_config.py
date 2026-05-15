from __future__ import annotations

from pathlib import Path

import pytest

from door_gateway.config import parse_gateway_args


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_gateway_config_uses_number_cams_from_device_env(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "config.env", "")
    _write(tmp_path / "door_gateway.env", "SERIAL_PORT=/dev/null\n")
    _write(tmp_path / "device.env", "BUS_ID=BUS-001\nNUMBER_CAMS=4\n")

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_door_daemon.py",
            "--config-env-file",
            str(tmp_path / "config.env"),
            "--env-file",
            str(tmp_path / "door_gateway.env"),
            "--device-env-file",
            str(tmp_path / "device.env"),
        ],
    )

    config = parse_gateway_args()

    assert config.door_count == 4


def test_gateway_config_door_count_overrides_number_cams(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "config.env", "")
    _write(tmp_path / "door_gateway.env", "SERIAL_PORT=/dev/null\nDOOR_COUNT=3\n")
    _write(tmp_path / "device.env", "BUS_ID=BUS-001\nNUMBER_CAMS=4\n")

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_door_daemon.py",
            "--config-env-file",
            str(tmp_path / "config.env"),
            "--env-file",
            str(tmp_path / "door_gateway.env"),
            "--device-env-file",
            str(tmp_path / "device.env"),
        ],
    )

    config = parse_gateway_args()

    assert config.door_count == 3


def test_gateway_config_rejects_invalid_number_cams(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "config.env", "")
    _write(tmp_path / "door_gateway.env", "SERIAL_PORT=/dev/null\n")
    _write(tmp_path / "device.env", "BUS_ID=BUS-001\nNUMBER_CAMS=5\n")

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_door_daemon.py",
            "--config-env-file",
            str(tmp_path / "config.env"),
            "--env-file",
            str(tmp_path / "door_gateway.env"),
            "--device-env-file",
            str(tmp_path / "device.env"),
        ],
    )

    with pytest.raises(SystemExit):
        parse_gateway_args()
