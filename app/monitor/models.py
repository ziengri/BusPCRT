from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def isoformat_utc(dt: datetime) -> str:
    normalized = dt.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def isoformat_from_epoch(seconds: float) -> str:
    return isoformat_utc(datetime.fromtimestamp(seconds, tz=timezone.utc))


def canonical_json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass
class CameraTarget:
    camera_id: int
    name: str
    ip: str
    source: str | None = None
    port: int = 554


@dataclass
class CameraStatus:
    camera_id: int
    name: str
    ip: str
    source: str | None
    reachable: bool
    checked_at: str
    last_online_at: str | None
    latency_ms: int | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "cameraId": self.camera_id,
            "name": self.name,
            "ip": self.ip,
            "reachable": self.reachable,
            "checkedAt": self.checked_at,
        }
        if self.source:
            payload["source"] = self.source
        if self.last_online_at is not None:
            payload["lastOnlineAt"] = self.last_online_at
        if self.latency_ms is not None:
            payload["latencyMs"] = self.latency_ms
        return payload


@dataclass
class ConnectivityStatus:
    api_reachable: bool
    checked_at: str
    api_last_online_at: str | None
    latency_ms: int | None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "apiReachable": self.api_reachable,
            "checkedAt": self.checked_at,
        }
        if self.api_last_online_at is not None:
            payload["apiLastOnlineAt"] = self.api_last_online_at
        if self.latency_ms is not None:
            payload["latencyMs"] = self.latency_ms
        return payload


@dataclass
class ServiceStatus:
    name: str
    status: str
    sub_state: str | None
    result: str | None
    exec_main_status: int | None
    active_enter_timestamp: str | None
    checked_at: str
    monitor_state: str

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "checkedAt": self.checked_at,
            "monitorState": self.monitor_state,
        }
        if self.sub_state is not None:
            payload["subState"] = self.sub_state
        if self.result is not None:
            payload["result"] = self.result
        if self.exec_main_status is not None:
            payload["execMainStatus"] = self.exec_main_status
        if self.active_enter_timestamp is not None:
            payload["activeEnterTimestamp"] = self.active_enter_timestamp
        return payload


@dataclass
class StorageStatus:
    path: str
    total_bytes: int
    free_bytes: int
    used_percent: float
    sessions_bytes: int
    directories: dict[str, int]
    threshold: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "totalBytes": self.total_bytes,
            "freeBytes": self.free_bytes,
            "usedPercent": self.used_percent,
            "sessionsBytes": self.sessions_bytes,
            "directories": self.directories,
            "threshold": self.threshold,
        }


@dataclass
class MonitorEvent:
    event_id: str
    occurred_at: str
    kind: str
    component: str
    severity: str
    message: str
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "eventId": self.event_id,
            "occurredAt": self.occurred_at,
            "kind": self.kind,
            "component": self.component,
            "severity": self.severity,
            "message": self.message,
        }
        if self.details is not None:
            payload["details"] = self.details
        return payload


def build_event_id(
    bus_id: str,
    kind: str,
    component: str,
    occurred_at: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> str:
    base = "|".join(
        [
            bus_id,
            kind,
            component,
            occurred_at,
            message,
            canonical_json(details),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()
