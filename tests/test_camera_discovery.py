from __future__ import annotations

from pathlib import Path

import pytest

from app.shared import discover_recorder_configs


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_discover_recorder_configs_sorts_by_camera_suffix(tmp_path: Path) -> None:
    _write(tmp_path / "recorder-cam10.env", "CAMERA_ID=cam10\nSOURCE=rtsp://10.0.0.10\nDOOR_CHANNEL=10\n")
    _write(tmp_path / "recorder-cam.env", "CAMERA_ID=cam1\nSOURCE=rtsp://10.0.0.1\nDOOR_CHANNEL=1\n")
    _write(tmp_path / "recorder-cam2.env", "CAMERA_ID=cam2\nSOURCE=rtsp://10.0.0.2\nDOOR_CHANNEL=2\n")

    configs = discover_recorder_configs(tmp_path)

    assert [config.camera_id for config in configs] == ["cam1", "cam2", "cam10"]


def test_discover_recorder_configs_ignores_blank_template(tmp_path: Path) -> None:
    _write(tmp_path / "recorder-cam.env", "CAMERA_ID=cam1\nSOURCE=rtsp://10.0.0.1\nDOOR_CHANNEL=1\n")
    _write(tmp_path / "recorder-cam4.env", "# template only\n")

    configs = discover_recorder_configs(tmp_path)

    assert [config.camera_id for config in configs] == ["cam1"]


def test_discover_recorder_configs_requires_complete_active_env(tmp_path: Path) -> None:
    _write(tmp_path / "recorder-cam4.env", "CAMERA_ID=cam4\nDOOR_CHANNEL=4\n")

    with pytest.raises(ValueError):
        discover_recorder_configs(tmp_path)


def test_discover_recorder_configs_filters_by_number_cams(tmp_path: Path) -> None:
    _write(tmp_path / "recorder-cam.env", "CAMERA_ID=cam1\nSOURCE=rtsp://10.0.0.1\nDOOR_CHANNEL=1\n")
    _write(tmp_path / "recorder-cam2.env", "CAMERA_ID=cam2\nSOURCE=rtsp://10.0.0.2\nDOOR_CHANNEL=2\n")
    _write(tmp_path / "recorder-cam3.env", "CAMERA_ID=cam3\nSOURCE=rtsp://10.0.0.3\nDOOR_CHANNEL=3\n")
    _write(tmp_path / "recorder-cam4.env", "CAMERA_ID=cam4\nSOURCE=rtsp://10.0.0.4\nDOOR_CHANNEL=4\n")

    three = discover_recorder_configs(tmp_path, number_cams=3)
    four = discover_recorder_configs(tmp_path, number_cams=4)

    assert [config.camera_id for config in three] == ["cam1", "cam2", "cam3"]
    assert [config.camera_id for config in four] == ["cam1", "cam2", "cam3", "cam4"]


def test_discover_recorder_configs_ignores_inactive_incomplete_cam4(tmp_path: Path) -> None:
    _write(tmp_path / "recorder-cam.env", "CAMERA_ID=cam1\nSOURCE=rtsp://10.0.0.1\nDOOR_CHANNEL=1\n")
    _write(tmp_path / "recorder-cam2.env", "CAMERA_ID=cam2\nSOURCE=rtsp://10.0.0.2\nDOOR_CHANNEL=2\n")
    _write(tmp_path / "recorder-cam3.env", "CAMERA_ID=cam3\nSOURCE=rtsp://10.0.0.3\nDOOR_CHANNEL=3\n")
    _write(tmp_path / "recorder-cam4.env", "CAMERA_ID=cam4\nDOOR_CHANNEL=4\n")

    configs = discover_recorder_configs(tmp_path, number_cams=3)

    assert [config.camera_id for config in configs] == ["cam1", "cam2", "cam3"]


def test_discover_recorder_configs_rejects_invalid_number_cams(tmp_path: Path) -> None:
    _write(tmp_path / "recorder-cam.env", "CAMERA_ID=cam1\nSOURCE=rtsp://10.0.0.1\nDOOR_CHANNEL=1\n")

    with pytest.raises(ValueError):
        discover_recorder_configs(tmp_path, number_cams=5)
