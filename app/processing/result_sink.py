from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib import error, parse, request

from app.shared.types import ProcessedResult

LOGGER = logging.getLogger(__name__)


class ResultSink(Protocol):
    def write(self, result: ProcessedResult) -> None:
        ...


class CsvResultSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, result: ProcessedResult) -> None:
        need_header = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            if need_header:
                writer.writerow(["date", "id", "totalIn", "totalOut"])
            writer.writerow([result.date, result.id, result.total_in, result.total_out])


class TimelineApiResultSink:
    def __init__(
        self,
        url: str,
        bus: str = "BUS320",
        timeout_s: float = 10.0,
        buses_url: str | None = None,
        x_auth: str = "pcrt!af3g",
    ):
        self.url = url
        self.buses_url = buses_url or self._derive_buses_url(url)
        self.bus = bus
        self.timeout_s = float(timeout_s)
        self.x_auth = x_auth
        self._known_buses: set[str] = set()
        self._buses_cache_loaded = False

    @staticmethod
    def _derive_buses_url(timeline_url: str) -> str:
        parsed = parse.urlsplit(timeline_url)
        return parse.urlunsplit((parsed.scheme, parsed.netloc, "/api/v1/buses", "", ""))

    @staticmethod
    def _camera_number(camera_id: str) -> str:
        match = re.search(r"\d+", camera_id)
        return match.group(0) if match else camera_id

    @staticmethod
    def _ensure_timeline_date(value: str) -> str:
        # Prefer provided value from service; fallback to current time on parse issues.
        try:
            parsed = datetime.strptime(value, "%d.%m.%YT%H:%M")
            return parsed.strftime("%d.%m.%YT%H:%M")
        except ValueError:
            return datetime.now().strftime("%d.%m.%YT%H:%M")

    def _http_form(self, url: str, payload: dict, method: str = "POST") -> tuple[int, str]:
        encoded = parse.urlencode(payload).encode("utf-8")
        req = request.Request(
            url,
            data=encoded,
            method=method,
            headers={
                "accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-AUTH": self.x_auth,
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8", errors="replace")
                return status, body
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return int(exc.code), body

    def _http_get_json(self, url: str) -> tuple[int, object]:
        req = request.Request(
            url,
            method="GET",
            headers={
                "accept": "application/json",
                "X-AUTH": self.x_auth,
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            status = int(exc.code)
            body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body) if body else None
        except json.JSONDecodeError:
            data = None
        return status, data

    def _load_buses_cache(self) -> None:
        if self._buses_cache_loaded:
            return
        status, data = self._http_get_json(self.buses_url)
        if status >= 400:
            raise RuntimeError(f"Bus API returned HTTP {status} on list buses")
        self._known_buses.clear()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    bus_id = item.get("bus")
                    if isinstance(bus_id, str) and bus_id:
                        self._known_buses.add(bus_id)
        self._buses_cache_loaded = True

    def _ensure_bus_exists(self, bus: str, camera_count: int) -> None:
        self._load_buses_cache()
        if bus in self._known_buses:
            return

        payload = {
            "bus": bus,
            "cameraCount": int(max(1, camera_count)),
        }
        status, body = self._http_form(self.buses_url, payload=payload, method="POST")
        if status not in (200, 201, 409):
            raise RuntimeError(f"Bus API returned HTTP {status} on create bus: {body}")

        # Refresh cache after creation or possible race (409 already exists).
        self._buses_cache_loaded = False
        self._load_buses_cache()
        if bus not in self._known_buses:
            raise RuntimeError(f"Bus '{bus}' was not found after create attempt")
        LOGGER.info("Bus ensured in API: %s (cameraCount=%s)", bus, payload["cameraCount"])

    def build_payload(self, result: ProcessedResult) -> dict[str, int | str]:
        cam_token = self._camera_number(result.id)
        try:
            cam_int = int(cam_token)
        except ValueError:
            cam_int = 1
        return {
            "bus": self.bus,
            "cam": cam_int,
            "date": self._ensure_timeline_date(result.date),
            "in": int(result.total_in),
            "out": int(result.total_out),
        }

    def send_payload(self, payload: dict[str, int | str]) -> None:
        bus = str(payload.get("bus", self.bus))
        cam = int(payload.get("cam", 1))
        self._ensure_bus_exists(bus, camera_count=cam)
        status, body = self._http_form(self.url, payload=payload, method="POST")
        if status >= 400:
            raise RuntimeError(f"Timeline API returned HTTP {status}: {body}")
        LOGGER.info("Timeline API response: status=%s body=%s", status, body)

    def write(self, result: ProcessedResult) -> None:
        payload = self.build_payload(result)
        self.send_payload(payload)


class BufferedTimelineResultSink:
    def __init__(
        self,
        url: str,
        bus: str = "BUS320",
        timeout_s: float = 10.0,
        outbox_db: str | Path = "sessions/outbox/timeline_outbox.sqlite",
        buses_url: str | None = None,
    ):
        self.timeline_sink = TimelineApiResultSink(
            url=url,
            bus=bus,
            timeout_s=timeout_s,
            buses_url=buses_url,
        )
        self.outbox_db = Path(outbox_db)
        self.outbox_db.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.outbox_db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS timeline_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at REAL,
                    last_error TEXT
                )
                """
            )
            conn.commit()

    def _enqueue(self, payload: dict[str, int | str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO timeline_outbox(payload, created_at, attempts) VALUES (?, ?, 0)",
                (json.dumps(payload, separators=(",", ":")), time.time()),
            )
            conn.commit()

    def _get_oldest_pending(self) -> sqlite3.Row | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, payload, attempts FROM timeline_outbox ORDER BY id ASC LIMIT 1"
            ).fetchone()
            return row

    def _mark_failed_attempt(self, row_id: int, error_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE timeline_outbox
                SET attempts = attempts + 1,
                    last_attempt_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (time.time(), error_text[:2000], row_id),
            )
            conn.commit()

    def _delete_row(self, row_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM timeline_outbox WHERE id = ?", (row_id,))
            conn.commit()

    def flush_pending(self) -> None:
        while True:
            row = self._get_oldest_pending()
            if row is None:
                return

            row_id = int(row["id"])
            try:
                payload = json.loads(str(row["payload"]))
                if not isinstance(payload, dict):
                    raise RuntimeError("Outbox payload is not a JSON object")
                self.timeline_sink.send_payload(payload)
                self._delete_row(row_id)
            except Exception as exc:  # noqa: BLE001
                self._mark_failed_attempt(row_id, str(exc))
                LOGGER.warning("Outbox send failed for id=%s, will retry later: %s", row_id, exc)
                return

    def write(self, result: ProcessedResult) -> None:
        payload = self.timeline_sink.build_payload(result)
        self._enqueue(payload)
        self.flush_pending()


class CombinedResultSink:
    def __init__(self, *sinks: ResultSink):
        self._sinks = sinks

    def write(self, result: ProcessedResult) -> None:
        for sink in self._sinks:
            sink.write(result)
