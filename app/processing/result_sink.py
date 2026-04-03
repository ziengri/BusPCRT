from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib import parse, request

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
    ):
        self.url = url
        self.bus = bus
        self.timeout_s = float(timeout_s)

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

    def write(self, result: ProcessedResult) -> None:
        payload = {
            "bus": self.bus,
            "cam": self._camera_number(result.id),
            "date": self._ensure_timeline_date(result.date),
            "in": str(result.total_in),
            "out": str(result.total_out),
        }
        encoded = parse.urlencode(payload).encode("utf-8")
        req = request.Request(
            self.url,
            data=encoded,
            method="POST",
            headers={
                "accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout_s) as resp:
                status = getattr(resp, "status", 200)
                body = resp.read().decode("utf-8", errors="replace")
                if status >= 400:
                    raise RuntimeError(f"Timeline API returned HTTP {status}: {body}")
                LOGGER.info("Timeline API response: status=%s body=%s", status, body)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to send result to timeline API: {exc}") from exc


class CombinedResultSink:
    def __init__(self, *sinks: ResultSink):
        self._sinks = sinks

    def write(self, result: ProcessedResult) -> None:
        for sink in self._sinks:
            sink.write(result)
