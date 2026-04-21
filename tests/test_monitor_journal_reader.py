from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.monitor.config import MonitorConfig
from app.monitor.journal_reader import build_app_error_event, read_journal_entries
from app.monitor.models import CameraTarget
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
        journal_units=("buspcrt-processor.service",),
    )


def test_read_journal_entries_and_ignore_non_errors(monkeypatch) -> None:
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "__CURSOR": "cursor-1",
                    "__REALTIME_TIMESTAMP": "1767261600000000",
                    "MESSAGE": "2026-01-01 | INFO | [processor] | app | all good",
                    "SYSLOG_IDENTIFIER": "python",
                }
            ),
            json.dumps(
                {
                    "__CURSOR": "cursor-2",
                    "__REALTIME_TIMESTAMP": "1767261660000000",
                    "MESSAGE": "2026-01-01 | ERROR | [processor] | app | boom\nTraceback...",
                    "SYSLOG_IDENTIFIER": "python",
                }
            ),
            "-- cursor: cursor-2",
        ]
    )

    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )

    entries, cursor = read_journal_entries(
        "buspcrt-processor.service",
        cursor=None,
        bootstrap_since="-5m",
        timeout_s=1.0,
    )

    assert cursor == "cursor-2"
    assert len(entries) == 2

    event, normalized = build_app_error_event("BUS-001", entries[0])
    assert event is None
    assert normalized is None

    error_event, normalized = build_app_error_event("BUS-001", entries[1])
    assert error_event is not None
    assert error_event.severity == "error"
    assert error_event.message.endswith("boom")
    assert normalized == "2026-01-01 | error | [processor] | app | boom"


def test_app_error_dedup_window(tmp_path: Path) -> None:
    service = MonitorService(_config(tmp_path), outbox=MonitorOutbox(tmp_path / "monitor.sqlite"), api_client=_ClientStub())

    assert service._should_emit_app_error("buspcrt-processor.service", "boom", "2026-01-01T10:00:00Z") is True
    assert service._should_emit_app_error("buspcrt-processor.service", "boom", "2026-01-01T10:05:00Z") is False
    assert service._should_emit_app_error("buspcrt-processor.service", "boom", "2026-01-01T10:11:00Z") is True
