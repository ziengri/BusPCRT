from __future__ import annotations

import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Iterable

from .client import MonitorApiClient
from .models import (
    CameraStatus,
    CameraTarget,
    ConnectivityStatus,
    ServiceStatus,
    StorageStatus,
    isoformat_from_epoch,
    isoformat_utc,
    utc_now,
)

LOGGER = logging.getLogger(__name__)
SYSTEMCTL_PROPS = (
    "ActiveState",
    "SubState",
    "Result",
    "ExecMainStatus",
    "ExecMainStartTimestampMonotonic",
    "ActiveEnterTimestamp",
)
SESSIONS_SUBDIRS = ("active", "ready", "processing", "failed", "saved", "debug", "outbox")


def _safe_int(value: str | None) -> int | None:
    if value in (None, "", "n/a"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def probe_camera(
    target: CameraTarget,
    timeout_s: float,
    *,
    checked_at: str | None = None,
    last_online_at: str | None = None,
) -> CameraStatus:
    checked_at = checked_at or isoformat_utc(utc_now())
    started_at = time.perf_counter()
    reachable = False
    latency_ms: int | None = None

    try:
        with socket.create_connection((target.ip, target.port), timeout=timeout_s):
            reachable = True
            latency_ms = int((time.perf_counter() - started_at) * 1000)
    except OSError:
        reachable = False

    if reachable:
        last_online_at = checked_at

    return CameraStatus(
        camera_id=target.camera_id,
        name=target.name,
        ip=target.ip,
        source=target.source,
        reachable=reachable,
        checked_at=checked_at,
        last_online_at=last_online_at,
        latency_ms=latency_ms,
    )


def probe_connectivity(
    client: MonitorApiClient,
    *,
    checked_at: str | None = None,
    last_online_at: str | None = None,
) -> ConnectivityStatus:
    checked_at = checked_at or isoformat_utc(utc_now())
    try:
        reachable, latency_ms = client.check_health()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Monitoring API health probe failed: %s", exc)
        reachable = False
        latency_ms = None

    if reachable:
        last_online_at = checked_at

    return ConnectivityStatus(
        api_reachable=reachable,
        checked_at=checked_at,
        api_last_online_at=last_online_at,
        latency_ms=latency_ms,
    )


def parse_systemctl_show(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key] = value
    return parsed


def _service_monitor_state(name: str, active_state: str, result: str, exec_main_status: int | None) -> str:
    if name == "buspcrt-updater.service":
        if active_state == "failed":
            return "error"
        if result not in ("", "success") and (exec_main_status not in (None, 0)):
            return "error"
        return "ok"

    if name == "buspcrt-updater.timer":
        return "ok" if active_state == "active" else "error"

    return "ok" if active_state == "active" else "error"


def probe_service(unit_name: str, timeout_s: float, *, checked_at: str | None = None) -> ServiceStatus:
    checked_at = checked_at or isoformat_utc(utc_now())
    cmd = [
        "systemctl",
        "show",
        unit_name,
        f"--property={','.join(SYSTEMCTL_PROPS)}",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("systemctl show failed for %s: %s", unit_name, exc)
        return ServiceStatus(
            name=unit_name,
            status="unknown",
            sub_state=None,
            result="probe-error",
            exec_main_status=None,
            active_enter_timestamp=None,
            checked_at=checked_at,
            monitor_state="error",
        )

    parsed = parse_systemctl_show(proc.stdout)
    active_state = parsed.get("ActiveState", "unknown")
    sub_state = parsed.get("SubState")
    result = parsed.get("Result")
    exec_main_status = _safe_int(parsed.get("ExecMainStatus"))
    active_enter_timestamp = parsed.get("ActiveEnterTimestamp") or None
    monitor_state = _service_monitor_state(
        unit_name,
        active_state=active_state,
        result=result or "",
        exec_main_status=exec_main_status,
    )
    if proc.returncode != 0:
        monitor_state = "error"
        result = result or "probe-error"

    return ServiceStatus(
        name=unit_name,
        status=active_state,
        sub_state=sub_state,
        result=result,
        exec_main_status=exec_main_status,
        active_enter_timestamp=active_enter_timestamp,
        checked_at=checked_at,
        monitor_state=monitor_state,
    )


def probe_services(units: Iterable[str], timeout_s: float, *, checked_at: str | None = None) -> list[ServiceStatus]:
    checked_at = checked_at or isoformat_utc(utc_now())
    return [probe_service(unit_name, timeout_s, checked_at=checked_at) for unit_name in units]


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for file_name in files:
            file_path = Path(root) / file_name
            try:
                total += file_path.stat().st_size
            except FileNotFoundError:
                continue
    return total


def compute_storage_status(
    sessions_dir: Path,
    *,
    warn_pct: float,
    crit_pct: float,
) -> StorageStatus:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(sessions_dir)
    used_percent = 0.0
    if usage.total > 0:
        used_percent = round(((usage.total - usage.free) / usage.total) * 100.0, 2)

    directories = {
        subdir: _directory_size(sessions_dir / subdir)
        for subdir in SESSIONS_SUBDIRS
    }
    sessions_bytes = sum(directories.values())
    if used_percent >= crit_pct:
        threshold = "critical"
    elif used_percent >= warn_pct:
        threshold = "warning"
    else:
        threshold = "normal"

    return StorageStatus(
        path=str(sessions_dir),
        total_bytes=int(usage.total),
        free_bytes=int(usage.free),
        used_percent=used_percent,
        sessions_bytes=sessions_bytes,
        directories=directories,
        threshold=threshold,
    )


def count_timeline_pending(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) FROM timeline_outbox").fetchone()
            return int(row[0]) if row is not None else 0
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Failed to count timeline pending rows in %s: %s", db_path, exc)
        return 0


def parse_journal_realtime_timestamp(value: str | None) -> str:
    if not value:
        return isoformat_utc(utc_now())
    try:
        micros = int(value)
    except ValueError:
        return isoformat_utc(utc_now())
    return isoformat_from_epoch(micros / 1_000_000.0)
