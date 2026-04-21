from __future__ import annotations

from pathlib import Path

import pytest

from app.monitor.config import parse_monitor_args


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_monitor_config_reads_bus_and_recorder_targets(monkeypatch, tmp_path: Path) -> None:
    _write(
        tmp_path / "config.env",
        "\n".join(
            [
                "SESSIONS_DIR=/var/lib/pcrt/sessions",
                "API_BASE_URL=http://example.com:8000",
                "API_X_AUTH=test-key",
            ]
        ),
    )
    _write(tmp_path / "monitor.env", "MONITOR_DB_PATH=/var/lib/pcrt/monitor.sqlite\n")
    _write(tmp_path / "device.env", "BUS_ID=BUS-001\n")
    _write(
        tmp_path / "recorder-cam.env",
        "CAMERA_ID=cam1\nSOURCE=rtsp://user:pass@192.168.0.3:554/stream\n",
    )
    _write(
        tmp_path / "recorder-cam2.env",
        "CAMERA_ID=cam2\nSOURCE=rtsp://user:pass@192.168.0.4:554/stream\n",
    )
    _write(
        tmp_path / "recorder-cam3.env",
        "CAMERA_ID=cam3\nSOURCE=rtsp://user:pass@192.168.0.5:554/stream\n",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_monitor.py",
            "--config-env-file",
            str(tmp_path / "config.env"),
            "--env-file",
            str(tmp_path / "monitor.env"),
            "--device-env-file",
            str(tmp_path / "device.env"),
        ],
    )

    config = parse_monitor_args()

    assert config.bus_id == "BUS-001"
    assert config.api_base_url == "http://example.com:8000"
    assert config.api_x_auth == "test-key"
    assert [target.ip for target in config.camera_targets] == [
        "192.168.0.3",
        "192.168.0.4",
        "192.168.0.5",
    ]


def test_monitor_config_falls_back_to_cam_ips(monkeypatch, tmp_path: Path) -> None:
    _write(
        tmp_path / "config.env",
        "\n".join(
            [
                "SESSIONS_DIR=/var/lib/pcrt/sessions",
                "API_BASE_URL=http://example.com:8000",
                "API_X_AUTH=test-key",
            ]
        ),
    )
    _write(
        tmp_path / "monitor.env",
        "\n".join(
            [
                "CAM1_IP=10.0.0.3",
                "CAM2_IP=10.0.0.4",
                "CAM3_IP=10.0.0.5",
            ]
        ),
    )
    _write(tmp_path / "device.env", "BUS_ID=BUS-002\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_monitor.py",
            "--config-env-file",
            str(tmp_path / "config.env"),
            "--env-file",
            str(tmp_path / "monitor.env"),
            "--device-env-file",
            str(tmp_path / "device.env"),
        ],
    )

    config = parse_monitor_args()

    assert [target.ip for target in config.camera_targets] == ["10.0.0.3", "10.0.0.4", "10.0.0.5"]


def test_monitor_config_requires_bus_id(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path / "config.env", "SESSIONS_DIR=/var/lib/pcrt/sessions\n")
    _write(tmp_path / "monitor.env", "CAM1_IP=10.0.0.3\n")
    _write(tmp_path / "device.env", "")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_monitor.py",
            "--config-env-file",
            str(tmp_path / "config.env"),
            "--env-file",
            str(tmp_path / "monitor.env"),
            "--device-env-file",
            str(tmp_path / "device.env"),
        ],
    )

    with pytest.raises(SystemExit):
        parse_monitor_args()
