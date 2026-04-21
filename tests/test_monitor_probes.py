from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from app.monitor.client import MonitorApiClient
from app.monitor.models import CameraTarget
from app.monitor.probes import (
    compute_storage_status,
    count_timeline_pending,
    parse_systemctl_show,
    probe_camera,
    probe_connectivity,
    probe_service,
)


class _SocketOk:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_probe_camera_and_connectivity(monkeypatch) -> None:
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: _SocketOk())

    target = CameraTarget(camera_id=1, name="cam1", ip="192.168.0.3", source="rtsp://cam1")
    camera = probe_camera(target, timeout_s=0.1, checked_at="2026-01-01T10:00:00Z")

    assert camera.reachable is True
    assert camera.last_online_at == "2026-01-01T10:00:00Z"

    client = MonitorApiClient("http://example.com", "key", 1.0)
    monkeypatch.setattr(client, "check_health", lambda: (True, 12))
    connectivity = probe_connectivity(client, checked_at="2026-01-01T10:00:01Z")

    assert connectivity.api_reachable is True
    assert connectivity.api_last_online_at == "2026-01-01T10:00:01Z"
    assert connectivity.latency_ms == 12


def test_probe_service_and_parse_show(monkeypatch) -> None:
    stdout = "\n".join(
        [
            "ActiveState=active",
            "SubState=running",
            "Result=success",
            "ExecMainStatus=0",
            "ActiveEnterTimestamp=Tue 2026-01-01 10:00:00 UTC",
        ]
    )

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    parsed = parse_systemctl_show(stdout)
    service = probe_service("buspcrt-processor.service", timeout_s=0.1, checked_at="2026-01-01T10:00:00Z")

    assert parsed["ActiveState"] == "active"
    assert service.status == "active"
    assert service.monitor_state == "ok"
    assert service.exec_main_status == 0


def test_storage_and_timeline_count(monkeypatch, tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    (sessions_dir / "ready").mkdir(parents=True)
    (sessions_dir / "ready" / "video.mkv").write_bytes(b"12345")

    monkeypatch.setattr(
        "shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100, used=85, free=15),
    )
    storage = compute_storage_status(sessions_dir, warn_pct=80, crit_pct=90)

    assert storage.threshold == "warning"
    assert storage.directories["ready"] == 5

    db_path = tmp_path / "timeline.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE timeline_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT)")
    conn.execute("INSERT INTO timeline_outbox(payload) VALUES ('{}')")
    conn.execute("INSERT INTO timeline_outbox(payload) VALUES ('{}')")
    conn.commit()
    conn.close()

    assert count_timeline_pending(db_path) == 2
