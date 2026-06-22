from __future__ import annotations

from pathlib import Path

from app.monitor.config import MonitorConfig
from app.monitor.models import CameraStatus, CameraTarget
from app.monitor.outbox import MonitorOutbox
from app.monitor.service import MonitorService


class _ClientStub:
    def check_health(self):
        return True, 10

    def send_events(self, bus_id: str, events: list[dict]):
        return None

    def send_status(self, payload: dict):
        return None


def _config(tmp_path: Path) -> MonitorConfig:
    return MonitorConfig(
        bus_id="BUS-001",
        project_root=tmp_path,
        sessions_dir=tmp_path / "sessions",
        timeline_outbox_db=tmp_path / "timeline.sqlite",
        monitor_db_path=tmp_path / "monitor.sqlite",
        api_base_url="http://example.com",
        api_x_auth="test-key",
        interval_sec=30.0,
        api_timeout_sec=1.0,
        error_dedup_sec=600,
        event_batch_size=100,
        storage_warn_pct=80.0,
        storage_crit_pct=90.0,
        journal_bootstrap_since="-5m",
        camera_targets=(CameraTarget(camera_id=1, name="cam1", ip="192.168.0.3"),),
        monitored_units=("buspcrt-processor.service",),
        journal_units=(),
    )


def test_camera_transitions_and_last_online_state(monkeypatch, tmp_path: Path) -> None:
    config = _config(tmp_path)
    outbox = MonitorOutbox(config.monitor_db_path)
    service = MonitorService(config, outbox=outbox, api_client=_ClientStub())

    states = iter([True, False])
    last_online_inputs: list[str | None] = []

    def fake_probe_camera(target, timeout_s, *, checked_at, last_online_at):
        reachable = next(states)
        last_online_inputs.append(last_online_at)
        return CameraStatus(
            camera_id=target.camera_id,
            name=target.name,
            ip=target.ip,
            source=target.source,
            reachable=reachable,
            checked_at=checked_at,
            last_online_at=checked_at if reachable else last_online_at,
            latency_ms=5 if reachable else None,
        )

    monkeypatch.setattr("app.monitor.service.probe_camera", fake_probe_camera)

    first = service._camera_statuses("2026-01-01T10:00:00Z")
    first_events = service._camera_transition_events(first, occurred_at="2026-01-01T10:00:00Z")
    second = service._camera_statuses("2026-01-01T10:01:00Z")
    second_events = service._camera_transition_events(second, occurred_at="2026-01-01T10:01:00Z")

    assert first_events == []
    assert last_online_inputs == [None, "2026-01-01T10:00:00Z"]
    assert second[0]["lastOnlineAt"] == "2026-01-01T10:00:00Z"
    assert len(second_events) == 1
    assert second_events[0].kind == "camera.status_changed"
    assert second_events[0].severity == "warning"


def test_internet_transition_emits_single_event(tmp_path: Path) -> None:
    service = MonitorService(_config(tmp_path), outbox=MonitorOutbox(tmp_path / "monitor.sqlite"), api_client=_ClientStub())

    first = service._internet_transition_events({"apiReachable": True}, occurred_at="2026-01-01T10:00:00Z")
    second = service._internet_transition_events({"apiReachable": False}, occurred_at="2026-01-01T10:01:00Z")
    third = service._internet_transition_events({"apiReachable": False}, occurred_at="2026-01-01T10:02:00Z")

    assert first == []
    assert len(second) == 1
    assert second[0].kind == "internet.status_changed"
    assert third == []


def test_recorder_service_transition_does_not_emit_unhealthy_event(tmp_path: Path) -> None:
    service = MonitorService(_config(tmp_path), outbox=MonitorOutbox(tmp_path / "monitor.sqlite"), api_client=_ClientStub())

    first = service._service_transition_events(
        [{"name": "buspcrt-recorder@cam1.service", "monitorState": "ok"}],
        occurred_at="2026-01-01T10:00:00Z",
    )
    second = service._service_transition_events(
        [{"name": "buspcrt-recorder@cam1.service", "monitorState": "error", "status": "failed"}],
        occurred_at="2026-01-01T10:01:00Z",
    )

    assert first == []
    assert second == []
