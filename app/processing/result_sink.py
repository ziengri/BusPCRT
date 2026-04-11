from __future__ import annotations

import csv
import json
import logging
import re
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
    ):
        self.url = url
        self.buses_url = buses_url or self._derive_buses_url(url)
        self.bus = bus
        self.timeout_s = float(timeout_s)
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
        req = request.Request(url, method="GET", headers={"accept": "application/json"})
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

    def write(self, result: ProcessedResult) -> None:
        cam_token = self._camera_number(result.id)
        try:
            cam_int = int(cam_token)
        except ValueError:
            cam_int = 1

        self._ensure_bus_exists(self.bus, camera_count=cam_int)

        payload = {
            "bus": self.bus,
            "cam": cam_int,
            "date": self._ensure_timeline_date(result.date),
            "in": int(result.total_in),
            "out": int(result.total_out),
        }
        status, body = self._http_form(self.url, payload=payload, method="POST")
        if status >= 400:
            raise RuntimeError(f"Timeline API returned HTTP {status}: {body}")
        LOGGER.info("Timeline API response: status=%s body=%s", status, body)


class CombinedResultSink:
    def __init__(self, *sinks: ResultSink):
        self._sinks = sinks

    def write(self, result: ProcessedResult) -> None:
        for sink in self._sinks:
            sink.write(result)
