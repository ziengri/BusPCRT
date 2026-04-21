from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.monitor.client import MonitorApiClient
from app.monitor.config import MonitorConfig
from app.monitor.models import CameraTarget
from app.monitor.outbox import MonitorOutbox
from app.monitor.service import MonitorService


class _Response:
    def __init__(self, status: int = 200, body: str = '{"status":"ok"}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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


def test_monitor_client_sends_json_with_auth(monkeypatch) -> None:
    sent_requests = []

    def fake_urlopen(req, timeout):
        sent_requests.append(req)
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = MonitorApiClient("http://example.com", "test-key", 1.0)

    client.send_status({"bus": "BUS-001", "reportedAt": "2026-01-01T10:00:00Z"})
    client.send_events(
        "BUS-001",
        [
            {
                "eventId": "evt-1",
                "occurredAt": "2026-01-01T10:00:00Z",
                "kind": "camera.status_changed",
                "component": "camera-1",
                "severity": "warning",
                "message": "Camera 1 is offline",
            }
        ],
    )

    assert sent_requests[0].full_url == "http://example.com/api/v1/device-status"
    assert sent_requests[0].get_header("X-auth") == "test-key"
    assert json.loads(sent_requests[1].data.decode("utf-8"))["bus"] == "BUS-001"


def test_reported_at_is_monotonic(tmp_path: Path) -> None:
    service = MonitorService(_config(tmp_path), outbox=MonitorOutbox(tmp_path / "monitor.sqlite"))

    first = service._next_reported_at()
    second = service._next_reported_at()

    assert second > first


def test_timeline_sink_uses_env_or_explicit_auth(monkeypatch) -> None:
    if sys.version_info < (3, 10):
        pytest.skip("Project runtime is Python 3.12; Timeline sink imports are not testable on Python 3.8.")

    from app.processing.result_sink import TimelineApiResultSink

    monkeypatch.setenv("API_X_AUTH", "from-env")
    sink = TimelineApiResultSink(url="http://example.com/api/v1/timeline")
    explicit = TimelineApiResultSink(url="http://example.com/api/v1/timeline", x_auth="explicit")

    assert sink.x_auth == "from-env"
    assert explicit.x_auth == "explicit"
