from __future__ import annotations

import contextlib
import io
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.ctl as ctl
from app.monitor.outbox import MonitorOutbox
from app.shared import RecorderConfig


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _runtime(tmp_path: Path, *, number_cams: int = 4, door_count: int | None = None) -> ctl.RuntimeConfig:
    active_recorders = [
        RecorderConfig(
            camera_id="cam1",
            source="rtsp://cam1",
            door_channel=1,
            env_path=tmp_path / "recorder-cam.env",
            source_host="cam1",
        ),
        RecorderConfig(
            camera_id="cam2",
            source="rtsp://cam2",
            door_channel=2,
            env_path=tmp_path / "recorder-cam2.env",
            source_host="cam2",
        ),
        RecorderConfig(
            camera_id="cam3",
            source="rtsp://cam3",
            door_channel=3,
            env_path=tmp_path / "recorder-cam3.env",
            source_host="cam3",
        ),
        RecorderConfig(
            camera_id="cam4",
            source="rtsp://cam4",
            door_channel=4,
            env_path=tmp_path / "recorder-cam4.env",
            source_host="cam4",
        ),
    ][:number_cams]
    return ctl.RuntimeConfig(
        project_root=tmp_path,
        config_env_path=tmp_path / "config.env",
        device_env_path=tmp_path / "device.env",
        monitor_env_path=tmp_path / "monitor.env",
        door_gateway_env_path=tmp_path / "door_gateway.env",
        bus_id="BUS-001",
        monitor_interval_sec=60.0,
        monitor_db_path=tmp_path / "monitor.sqlite",
        zmq_ipc_endpoint="ipc:///run/doors.sock",
        number_cams=number_cams,
        door_count=door_count or number_cams,
        recorder_configs=tuple(active_recorders),
    )


def test_resolve_units_supports_group_alias(tmp_path: Path) -> None:
    rows = ctl.resolve_units(_runtime(tmp_path), ["cams"], allow_groups=True)
    assert [unit for _alias, unit in rows] == [
        "buspcrt-recorder@cam1.service",
        "buspcrt-recorder@cam2.service",
        "buspcrt-recorder@cam3.service",
        "buspcrt-recorder@cam4.service",
    ]


def test_resolve_units_filters_cams_by_number_cams(tmp_path: Path) -> None:
    rows = ctl.resolve_units(_runtime(tmp_path, number_cams=3), ["cams"], allow_groups=True)

    assert [unit for _alias, unit in rows] == [
        "buspcrt-recorder@cam1.service",
        "buspcrt-recorder@cam2.service",
        "buspcrt-recorder@cam3.service",
    ]


def test_resolve_units_rejects_group_for_mutating_commands(tmp_path: Path) -> None:
    with pytest.raises(ctl.CtlError):
        ctl.resolve_units(_runtime(tmp_path), ["cams"], allow_groups=False)


def test_build_summary_marks_stale_snapshot(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    outbox = MonitorOutbox(runtime.monitor_db_path)
    outbox.set_last_status(
        {
            "bus": "BUS-001",
            "reportedAt": "2026-01-01T10:00:00Z",
            "connectivity": {"apiReachable": True},
            "cameras": [
                {"cameraId": 1, "reachable": True},
                {"cameraId": 2, "reachable": True},
                {"cameraId": 3, "reachable": True},
                {"cameraId": 4, "reachable": True},
            ],
            "buffers": {"monitorPendingEvents": 0},
        },
        "2026-01-01T10:00:00Z",
    )

    def fake_unit_status(alias, unit):
        return ctl.UnitStatus(
            alias=alias,
            unit=unit,
            installed=True,
            active=True,
            description=None,
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
            result="success",
            exec_main_status=0,
            active_enter_timestamp=None,
        )

    class _FakeDatetime:
        @staticmethod
        def now(tz):
            return datetime(2026, 1, 1, 10, 5, 0, tzinfo=tz)

        @staticmethod
        def fromisoformat(value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(ctl, "unit_status", fake_unit_status)
    monkeypatch.setattr(ctl, "datetime", _FakeDatetime)

    summary = ctl.build_summary(runtime)

    assert summary["monitorSnapshotStale"] is True
    assert summary["health"] == "degraded"


def test_run_logs_for_cams_builds_multi_unit_journalctl(monkeypatch) -> None:
    calls = []
    runtime = _runtime(Path("/tmp/pcrt-cli-test"))

    def fake_run(cmd, check=False, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ctl.subprocess, "run", fake_run)

    exit_code = ctl.run_logs(runtime, "cams", lines=50, follow=False)

    assert exit_code == 0
    assert calls[0][:3] == ["journalctl", "-u", "buspcrt-recorder@cam1.service"]
    assert "-u" in calls[0]
    assert "buspcrt-recorder@cam2.service" in calls[0]
    assert "buspcrt-recorder@cam3.service" in calls[0]
    assert "buspcrt-recorder@cam4.service" in calls[0]


def test_unit_status_marks_instance_unit_installed_and_active(monkeypatch) -> None:
    calls = []

    def fake_run(cmd, check=False, capture_output=False, text=False, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["systemctl", "show"]:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "LoadState=loaded\n"
                    "ActiveState=active\n"
                    "SubState=running\n"
                    "Result=success\n"
                    "ExecMainStatus=0\n"
                ),
            )
        if cmd[:3] == ["systemctl", "list-unit-files", "buspcrt-recorder@cam1.service"]:
            return SimpleNamespace(returncode=0, stdout="")
        if cmd[:3] == ["systemctl", "list-unit-files", "buspcrt-recorder@.service"]:
            return SimpleNamespace(returncode=0, stdout="buspcrt-recorder@.service enabled\n")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(ctl.subprocess, "run", fake_run)

    status = ctl.unit_status("cam1", "buspcrt-recorder@cam1.service")

    assert status.installed is True
    assert status.active is True
    assert calls[0][:2] == ["systemctl", "show"]


def test_run_doors_live_stops_and_restores_service(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    simulator = runtime.project_root / "scripts" / "door_zmq_terminal_sim.py"
    _write(simulator, "print('ok')\n")
    actions = []
    commands = []

    monkeypatch.setattr(ctl, "_was_active", lambda unit: True)
    monkeypatch.setattr(ctl, "_require_root", lambda action: None)
    monkeypatch.setattr(ctl, "run_systemctl_action", lambda action, units: actions.append((action, tuple(units))))
    monkeypatch.setattr(
        ctl.subprocess,
        "run",
        lambda cmd, *args, **kwargs: commands.append(cmd) or SimpleNamespace(returncode=0),
    )

    exit_code = ctl.run_doors_live(runtime)

    assert exit_code == 0
    assert actions == [
        ("stop", ("buspcrt-door-gateway.service",)),
        ("start", ("buspcrt-door-gateway.service",)),
    ]
    assert "--door-count" in commands[0]
    assert "4" in commands[0]


def test_run_doors_direct_stops_and_restores_service(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    script = runtime.project_root / "scripts" / "test_rs232_direct.py"
    _write(script, "print('ok')\n")
    actions = []
    commands = []

    monkeypatch.setattr(ctl, "_was_active", lambda unit: True)
    monkeypatch.setattr(ctl, "_require_root", lambda action: None)
    monkeypatch.setattr(ctl, "run_systemctl_action", lambda action, units: actions.append((action, tuple(units))))
    monkeypatch.setattr(
        ctl.subprocess,
        "run",
        lambda cmd, *args, **kwargs: commands.append(cmd) or SimpleNamespace(returncode=0),
    )

    exit_code = ctl.run_doors_direct(runtime)

    assert exit_code == 0
    assert actions == [
        ("stop", ("buspcrt-door-gateway.service",)),
        ("start", ("buspcrt-door-gateway.service",)),
    ]
    assert "--env-file" in commands[0]
    assert str(runtime.door_gateway_env_path) in commands[0]
    assert "--device-env-file" in commands[0]
    assert str(runtime.device_env_path) in commands[0]


def test_run_doors_direct_supports_serial_port_override(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    script = runtime.project_root / "scripts" / "test_rs232_direct.py"
    _write(script, "print('ok')\n")
    commands = []

    monkeypatch.setattr(ctl, "_was_active", lambda unit: False)
    monkeypatch.setattr(
        ctl.subprocess,
        "run",
        lambda cmd, *args, **kwargs: commands.append(cmd) or SimpleNamespace(returncode=0),
    )

    exit_code = ctl.run_doors_direct(runtime, serial_port_override="/dev/ttyS1")

    assert exit_code == 0
    assert "--serial-port" in commands[0]
    assert "/dev/ttyS1" in commands[0]


def test_run_record_stops_and_restores_matching_recorder(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _write(runtime.project_root / "recorder-cam4.env", "SOURCE=rtsp://cam4\nCAMERA_ID=cam4\nDOOR_CHANNEL=4\nFPS=25\n")
    actions = []
    captures = []

    monkeypatch.setattr(ctl, "_was_active", lambda unit: True)
    monkeypatch.setattr(ctl, "_require_root", lambda action: None)
    monkeypatch.setattr(ctl, "run_systemctl_action", lambda action, units: actions.append((action, tuple(units))))
    monkeypatch.setattr(
        ctl,
        "_manual_capture",
        lambda camera_alias, env_path, output_dir, duration: captures.append((camera_alias, env_path, output_dir, duration)) or {
            "camera": camera_alias,
            "metaPath": str(output_dir / "meta.json"),
        },
    )

    payload = ctl.run_record(runtime, "cam4", duration=12.0, output_dir=None)

    assert payload["camera"] == "cam4"
    assert captures[0][2] == Path("/var/lib/pcrt/manual-captures/cam4")
    assert actions == [
        ("stop", ("buspcrt-recorder@cam4.service",)),
        ("start", ("buspcrt-recorder@cam4.service",)),
    ]


def test_run_record_rejects_inactive_cam4_for_three_camera_bus(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, number_cams=3)

    with pytest.raises(ctl.CtlError, match="NUMBER_CAMS=3"):
        ctl.run_record(runtime, "cam4", duration=12.0, output_dir=None)


def test_main_status_json_outputs_machine_readable(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(ctl, "load_runtime_config", lambda args: runtime)
    monkeypatch.setattr(
        ctl,
        "build_status_payload",
        lambda runtime, targets: [{"alias": "cam4", "unit": "buspcrt-recorder@cam4.service", "installed": True, "active": True}],
    )
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = ctl.main(["status", "cam4", "--json"])

    assert exit_code == 0
    assert '"unit": "buspcrt-recorder@cam4.service"' in stdout.getvalue()


def test_main_help_command_prints_general_help() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = ctl.main(["help"])

    assert exit_code == 0
    assert "BusPCRT onboard operations CLI" in stdout.getvalue()


def test_main_help_command_for_specific_topic() -> None:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = ctl.main(["help", "record"])

    assert exit_code == 0
    assert "Manual camera recording" in stdout.getvalue()


def test_main_doors_direct_dispatches(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    calls = []

    monkeypatch.setattr(ctl, "load_runtime_config", lambda args: runtime)
    monkeypatch.setattr(
        ctl,
        "run_doors_direct",
        lambda runtime, serial_port_override=None: calls.append((runtime, serial_port_override)) or 0,
    )

    exit_code = ctl.main(["doors", "direct", "--serial-port", "/dev/ttyS1"])

    assert exit_code == 0
    assert calls == [(runtime, "/dev/ttyS1")]
