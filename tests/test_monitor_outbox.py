from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.monitor.models import MonitorEvent
from app.monitor.outbox import MonitorOutbox


def _event(event_id: str) -> MonitorEvent:
    return MonitorEvent(
        event_id=event_id,
        occurred_at="2026-01-01T10:00:00Z",
        kind="camera.status_changed",
        component="camera-1",
        severity="warning",
        message="Camera 1 is offline",
        details={"reachable": False},
    )


def test_pending_status_is_coalesced(tmp_path: Path) -> None:
    outbox = MonitorOutbox(tmp_path / "monitor.sqlite")
    outbox.set_pending_status({"bus": "BUS-1", "buffers": {"monitorPendingEvents": 1}}, "2026-01-01T10:00:00Z")
    outbox.set_pending_status({"bus": "BUS-1", "buffers": {"monitorPendingEvents": 2}}, "2026-01-01T10:00:01Z")

    row = outbox.get_pending_status()
    assert outbox.count_pending_status() == 1
    assert json.loads(str(row["payload"]))["buffers"]["monitorPendingEvents"] == 2


def test_event_queue_retry_and_send_delete(tmp_path: Path) -> None:
    outbox = MonitorOutbox(tmp_path / "monitor.sqlite")
    assert outbox.enqueue_events([_event("evt-1"), _event("evt-1"), _event("evt-2")]) == 2

    rows = outbox.get_due_events(limit=10)
    assert len(rows) == 2

    row_ids = [int(row["id"]) for row in rows]
    outbox.mark_events_failed(row_ids, "boom")
    conn = sqlite3.connect(tmp_path / "monitor.sqlite")
    failed_rows = conn.execute(
        "SELECT attempts, next_retry_at, last_error FROM event_outbox ORDER BY id ASC"
    ).fetchall()
    conn.close()

    assert failed_rows[0][0] == 1
    assert failed_rows[0][1] > 0
    assert failed_rows[0][2] == "boom"

    conn = sqlite3.connect(tmp_path / "monitor.sqlite")
    conn.execute("UPDATE event_outbox SET next_retry_at = 0")
    conn.commit()
    conn.close()

    retry_rows = outbox.get_due_events(limit=10)
    outbox.mark_events_sent([int(row["id"]) for row in retry_rows])
    assert outbox.count_pending_events() == 0
