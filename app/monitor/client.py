from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib import error, request

LOGGER = logging.getLogger(__name__)


class MonitorApiClient:
    def __init__(self, api_base_url: str, x_auth: str, timeout_s: float):
        self.api_base_url = api_base_url.rstrip("/")
        self.x_auth = x_auth
        self.timeout_s = float(timeout_s)

    @property
    def health_url(self) -> str:
        return f"{self.api_base_url}/health"

    @property
    def status_url(self) -> str:
        return f"{self.api_base_url}/api/v1/device-status"

    @property
    def events_url(self) -> str:
        return f"{self.api_base_url}/api/v1/device-events/batch"

    def _request_json(
        self,
        url: str,
        *,
        method: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, str, int | None]:
        headers = {
            "accept": "application/json",
            "X-AUTH": self.x_auth,
        }
        data: bytes | None = None
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url, data=data, method=method, headers=headers)
        started_at = time.perf_counter()
        try:
            with request.urlopen(req, timeout=self.timeout_s) as resp:
                status = int(getattr(resp, "status", 200))
                body = resp.read().decode("utf-8", errors="replace")
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                return status, body, latency_ms
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            return int(exc.code), body, latency_ms

    def check_health(self) -> tuple[bool, int | None]:
        status, _body, latency_ms = self._request_json(self.health_url, method="GET")
        healthy = status == 200
        if not healthy:
            LOGGER.warning("Monitoring health check failed: HTTP %s", status)
        return healthy, latency_ms

    def send_status(self, payload: dict[str, Any]) -> None:
        status, body, _latency_ms = self._request_json(self.status_url, method="POST", payload=payload)
        if status >= 400:
            raise RuntimeError(f"Device status API returned HTTP {status}: {body}")

    def send_events(self, bus_id: str, events: list[dict[str, Any]]) -> None:
        payload = {"bus": bus_id, "events": events}
        status, body, _latency_ms = self._request_json(self.events_url, method="POST", payload=payload)
        if status >= 400:
            raise RuntimeError(f"Device events API returned HTTP {status}: {body}")
