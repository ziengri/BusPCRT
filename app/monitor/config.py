from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib import parse

from dotenv import dotenv_values

from .models import CameraTarget

DEFAULT_API_BASE_URL = "http://5.129.252.183:8000"
DEFAULT_API_X_AUTH = "pcrt!af3g"
DEFAULT_MONITOR_UNITS = (
    "buspcrt-processor.service",
    "buspcrt-recorder@cam1.service",
    "buspcrt-recorder@cam2.service",
    "buspcrt-recorder@cam3.service",
    "buspcrt-door-gateway.service",
    "buspcrt-updater.timer",
    "buspcrt-updater.service",
)
DEFAULT_APP_ERROR_UNITS = (
    "buspcrt-processor.service",
    "buspcrt-recorder@cam1.service",
    "buspcrt-recorder@cam2.service",
    "buspcrt-recorder@cam3.service",
)
RECORDER_ENV_FILENAMES = ("recorder-cam.env", "recorder-cam2.env", "recorder-cam3.env")


@dataclass
class MonitorConfig:
    bus_id: str
    project_root: Path
    sessions_dir: Path
    timeline_outbox_db: Path
    monitor_db_path: Path
    api_base_url: str
    api_x_auth: str
    interval_sec: float
    api_timeout_sec: float
    error_dedup_sec: int
    event_batch_size: int
    storage_warn_pct: float
    storage_crit_pct: float
    journal_bootstrap_since: str
    camera_targets: tuple[CameraTarget, ...]
    monitored_units: tuple[str, ...]
    journal_units: tuple[str, ...]


def _load_env(path_value: str | None) -> dict[str, object]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value not in (None, "")}


def _derive_timeline_outbox_path(raw: dict[str, object]) -> str | None:
    explicit = raw.get("TIMELINE_OUTBOX_DB")
    if explicit:
        return str(explicit)

    sessions_dir = raw.get("SESSIONS_DIR")
    if not sessions_dir:
        return None
    return str(Path(str(sessions_dir)) / "outbox" / "timeline_outbox.sqlite")


def _env_defaults(
    env_file: str | None,
    config_env_file: str | None,
    device_env_file: str | None,
) -> dict[str, object]:
    raw: dict[str, object] = {}
    raw.update(_load_env(config_env_file))
    raw.update(_load_env(env_file))
    device_raw = _load_env(device_env_file)
    return {
        "bus_id": device_raw.get("BUS_ID"),
        "api_base_url": raw.get("API_BASE_URL"),
        "api_x_auth": raw.get("API_X_AUTH"),
        "sessions_dir": raw.get("SESSIONS_DIR"),
        "timeline_outbox_db": _derive_timeline_outbox_path(raw),
        "monitor_db_path": raw.get("MONITOR_DB_PATH"),
        "monitor_interval_sec": raw.get("MONITOR_INTERVAL_SEC"),
        "monitor_api_timeout_sec": raw.get("MONITOR_API_TIMEOUT_SEC"),
        "monitor_error_dedup_sec": raw.get("MONITOR_ERROR_DEDUP_SEC"),
        "monitor_event_batch_size": raw.get("MONITOR_EVENT_BATCH_SIZE"),
        "monitor_storage_warn_pct": raw.get("MONITOR_STORAGE_WARN_PCT"),
        "monitor_storage_crit_pct": raw.get("MONITOR_STORAGE_CRIT_PCT"),
        "monitor_journal_bootstrap_since": raw.get("MONITOR_JOURNAL_BOOTSTRAP_SINCE"),
        "cam1_ip": raw.get("CAM1_IP"),
        "cam2_ip": raw.get("CAM2_IP"),
        "cam3_ip": raw.get("CAM3_IP"),
    }


def _resolve_path(value: str | None, base_dir: Path, default: str) -> Path:
    path = Path(value) if value else Path(default)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _extract_rtsp_host(source: str | None) -> str | None:
    if not source:
        return None
    try:
        parsed = parse.urlsplit(source)
    except ValueError:
        return None
    return parsed.hostname


def _camera_number(camera_id: str, fallback: int) -> int:
    match = re.search(r"(\d+)", camera_id)
    if match:
        return int(match.group(1))
    return int(fallback)


def _load_camera_targets(project_root: Path, fallback_ips: dict[int, str], port: int = 554) -> tuple[CameraTarget, ...]:
    targets: list[CameraTarget] = []
    for index, env_name in enumerate(RECORDER_ENV_FILENAMES, start=1):
        env_path = project_root / env_name
        raw = _load_env(str(env_path))
        camera_name = str(raw.get("CAMERA_ID", f"cam{index}"))
        source = str(raw.get("SOURCE")) if raw.get("SOURCE") else None
        ip = _extract_rtsp_host(source) or fallback_ips.get(index)
        if not ip:
            continue
        targets.append(
            CameraTarget(
                camera_id=_camera_number(camera_name, index),
                name=camera_name,
                ip=ip,
                source=source,
                port=port,
            )
        )

    if targets:
        return tuple(sorted(targets, key=lambda item: item.camera_id))

    generated = [
        CameraTarget(camera_id=index, name=f"cam{index}", ip=ip, source=None, port=port)
        for index, ip in sorted(fallback_ips.items())
        if ip
    ]
    return tuple(generated)


def parse_monitor_args() -> MonitorConfig:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config-env-file", default="config.env")
    pre.add_argument("--device-env-file", default="/etc/pcrt/device.env")
    pre.add_argument("--env-file", default="monitor.env")
    pre_args, _ = pre.parse_known_args()
    env = _env_defaults(pre_args.env_file, pre_args.config_env_file, pre_args.device_env_file)

    parser = argparse.ArgumentParser(description="BusPCRT onboard monitoring service")
    parser.add_argument("--config-env-file", default=pre_args.config_env_file)
    parser.add_argument("--device-env-file", default=pre_args.device_env_file)
    parser.add_argument("--env-file", default=pre_args.env_file)
    parser.add_argument("--bus-id", dest="bus_id", default=None)
    parser.add_argument("--api-base-url", dest="api_base_url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--api-x-auth", dest="api_x_auth", default=DEFAULT_API_X_AUTH)
    parser.add_argument("--sessions-dir", dest="sessions_dir", default="sessions")
    parser.add_argument("--timeline-outbox-db", dest="timeline_outbox_db", default=None)
    parser.add_argument("--monitor-db-path", dest="monitor_db_path", default="/var/lib/pcrt/monitor.sqlite")
    parser.add_argument("--monitor-interval-sec", dest="monitor_interval_sec", type=float, default=30.0)
    parser.add_argument("--monitor-api-timeout-sec", dest="monitor_api_timeout_sec", type=float, default=5.0)
    parser.add_argument("--monitor-error-dedup-sec", dest="monitor_error_dedup_sec", type=int, default=600)
    parser.add_argument("--monitor-event-batch-size", dest="monitor_event_batch_size", type=int, default=100)
    parser.add_argument("--monitor-storage-warn-pct", dest="monitor_storage_warn_pct", type=float, default=80.0)
    parser.add_argument("--monitor-storage-crit-pct", dest="monitor_storage_crit_pct", type=float, default=90.0)
    parser.add_argument(
        "--monitor-journal-bootstrap-since",
        dest="monitor_journal_bootstrap_since",
        default="-5m",
    )
    parser.add_argument("--cam1-ip", dest="cam1_ip", default="192.168.0.3")
    parser.add_argument("--cam2-ip", dest="cam2_ip", default="192.168.0.4")
    parser.add_argument("--cam3-ip", dest="cam3_ip", default="192.168.0.5")
    parser.set_defaults(**{key: value for key, value in env.items() if value not in (None, "")})
    args = parser.parse_args()

    if not args.bus_id:
        parser.error("--bus-id is required (set /etc/pcrt/device.env BUS_ID)")

    config_env_path = Path(args.config_env_file).resolve()
    project_root = config_env_path.parent
    sessions_dir = _resolve_path(str(args.sessions_dir), project_root, "sessions")
    timeline_outbox_db = _resolve_path(args.timeline_outbox_db, project_root, "sessions/outbox/timeline_outbox.sqlite")
    monitor_db_path = _resolve_path(args.monitor_db_path, project_root, "monitor.sqlite")
    fallback_ips = {
        1: str(args.cam1_ip).strip(),
        2: str(args.cam2_ip).strip(),
        3: str(args.cam3_ip).strip(),
    }
    camera_targets = _load_camera_targets(project_root, fallback_ips=fallback_ips)
    if not camera_targets:
        parser.error("No camera targets could be resolved from recorder env files or fallback IPs")

    return MonitorConfig(
        bus_id=str(args.bus_id).strip(),
        project_root=project_root,
        sessions_dir=sessions_dir,
        timeline_outbox_db=timeline_outbox_db,
        monitor_db_path=monitor_db_path,
        api_base_url=str(args.api_base_url).rstrip("/"),
        api_x_auth=str(args.api_x_auth),
        interval_sec=float(args.monitor_interval_sec),
        api_timeout_sec=float(args.monitor_api_timeout_sec),
        error_dedup_sec=int(args.monitor_error_dedup_sec),
        event_batch_size=max(1, int(args.monitor_event_batch_size)),
        storage_warn_pct=float(args.monitor_storage_warn_pct),
        storage_crit_pct=float(args.monitor_storage_crit_pct),
        journal_bootstrap_since=str(args.monitor_journal_bootstrap_since),
        camera_targets=camera_targets,
        monitored_units=DEFAULT_MONITOR_UNITS,
        journal_units=DEFAULT_APP_ERROR_UNITS,
    )
