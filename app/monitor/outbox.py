from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .models import MonitorEvent


class MonitorOutbox:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS pending_status (
                    slot INTEGER PRIMARY KEY CHECK(slot = 1),
                    payload TEXT NOT NULL,
                    reported_at TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_attempt_at REAL
                );

                CREATE TABLE IF NOT EXISTS event_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_attempt_at REAL
                );

                CREATE TABLE IF NOT EXISTS local_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS journal_cursor (
                    unit TEXT PRIMARY KEY,
                    cursor TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            conn.commit()

    def set_pending_status(self, payload: dict[str, Any], reported_at: str) -> None:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_status(slot, payload, reported_at, updated_at, attempts, last_error, last_attempt_at)
                VALUES (1, ?, ?, ?, 0, NULL, NULL)
                ON CONFLICT(slot) DO UPDATE SET
                    payload = excluded.payload,
                    reported_at = excluded.reported_at,
                    updated_at = excluded.updated_at,
                    attempts = 0,
                    last_error = NULL,
                    last_attempt_at = NULL
                """,
                (serialized, reported_at, now),
            )
            conn.commit()

    def get_pending_status(self) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT payload, reported_at, attempts FROM pending_status WHERE slot = 1"
            ).fetchone()

    def mark_status_failed(self, error_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pending_status
                SET attempts = attempts + 1,
                    last_error = ?,
                    last_attempt_at = ?
                WHERE slot = 1
                """,
                (error_text[:2000], time.time()),
            )
            conn.commit()

    def clear_pending_status(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_status WHERE slot = 1")
            conn.commit()

    def count_pending_status(self) -> int:
        with self._connect() as conn:
            value = conn.execute("SELECT COUNT(*) FROM pending_status").fetchone()
            return int(value[0]) if value is not None else 0

    def enqueue_events(self, events: Iterable[MonitorEvent]) -> int:
        rows = [
            (
                event.event_id,
                event.occurred_at,
                json.dumps(event.to_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            )
            for event in events
        ]
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO event_outbox(event_id, occurred_at, payload, attempts, next_retry_at)
                VALUES (?, ?, ?, 0, 0)
                """,
                rows,
            )
            conn.commit()
            return int(conn.total_changes)

    def get_due_events(self, limit: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT id, event_id, payload, attempts
                    FROM event_outbox
                    WHERE next_retry_at <= ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (time.time(), int(limit)),
                )
            )

    def mark_events_sent(self, row_ids: Iterable[int]) -> None:
        row_ids = [int(row_id) for row_id in row_ids]
        if not row_ids:
            return
        placeholders = ",".join("?" for _ in row_ids)
        with self._connect() as conn:
            conn.execute(f"DELETE FROM event_outbox WHERE id IN ({placeholders})", row_ids)
            conn.commit()

    def mark_events_failed(self, row_ids: Iterable[int], error_text: str) -> None:
        now = time.time()
        with self._connect() as conn:
            for row_id in row_ids:
                row = conn.execute(
                    "SELECT attempts FROM event_outbox WHERE id = ?",
                    (int(row_id),),
                ).fetchone()
                if row is None:
                    continue
                attempts = int(row["attempts"]) + 1
                backoff_sec = min(300, 5 * (2**attempts))
                conn.execute(
                    """
                    UPDATE event_outbox
                    SET attempts = ?,
                        next_retry_at = ?,
                        last_error = ?,
                        last_attempt_at = ?
                    WHERE id = ?
                    """,
                    (attempts, now + backoff_sec, error_text[:2000], now, int(row_id)),
                )
            conn.commit()

    def count_pending_events(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM event_outbox").fetchone()
            return int(row[0]) if row is not None else 0

    def get_state(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM local_state WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row is not None else None

    def set_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO local_state(key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def delete_state(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM local_state WHERE key = ?", (key,))
            conn.commit()

    def get_cursor(self, unit: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT cursor FROM journal_cursor WHERE unit = ?", (unit,)).fetchone()
            return str(row["cursor"]) if row is not None else None

    def set_cursor(self, unit: str, cursor: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO journal_cursor(unit, cursor, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(unit) DO UPDATE SET
                    cursor = excluded.cursor,
                    updated_at = excluded.updated_at
                """,
                (unit, cursor, time.time()),
            )
            conn.commit()
