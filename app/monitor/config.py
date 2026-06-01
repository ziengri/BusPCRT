from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.shared import camera_numeric_id, discover_recorder_configs, parse_number_cams

from .models import CameraTarget

DEFAULT_API_BASE_URL = "http://72.56.239.131:8000"
DEFAULT_API_X_AUTH = "pcrt!af3g"
DEFAULT_FIXED_MONITOR_UNITS = (
    "buspcrt-processor.service",
    "buspcrt-door-gateway.service",
    "buspcrt-updater.timer",
    "buspcrt-updater.service",
)
DEFAULT_FIXED_APP_ERROR_UNITS = (
    "buspcrt-processor.service",
)


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
        "number_cams": device_raw.get("NUMBER_CAMS"),
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
    }


def _resolve_path(value: str | None, base_dir: Path, default: str) -> Path:
    path = Path(value) if value else Path(default)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _load_camera_targets(project_root: Path, *, number_cams: int | None = None, port: int = 554) -> tuple[CameraTarget, ...]:
    recorder_configs = discover_recorder_configs(project_root, number_cams=number_cams)
    targets: list[CameraTarget] = []
    for index, recorder in enumerate(recorder_configs, start=1):
        targets.append(
            CameraTarget(
                camera_id=camera_numeric_id(recorder.camera_id, index),
                name=recorder.camera_id,
                ip=recorder.source_host,
                source=recorder.source,
                port=port,
            )
        )
    return tuple(targets)


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
    parser.add_argument("--number-cams", dest="number_cams", type=int, default=None)
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
    parser.set_defaults(**{key: value for key, value in env.items() if value not in (None, "")})
    args = parser.parse_args()

    if not args.bus_id:
        parser.error("--bus-id is required (set /etc/pcrt/device.env BUS_ID)")
    try:
        number_cams = parse_number_cams(args.number_cams)
    except ValueError as exc:
        parser.error(str(exc))

    config_env_path = Path(args.config_env_file).resolve()
    project_root = config_env_path.parent
    sessions_dir = _resolve_path(str(args.sessions_dir), project_root, "sessions")
    timeline_outbox_db = _resolve_path(args.timeline_outbox_db, project_root, "sessions/outbox/timeline_outbox.sqlite")
    monitor_db_path = _resolve_path(args.monitor_db_path, project_root, "monitor.sqlite")
    try:
        camera_targets = _load_camera_targets(project_root, number_cams=number_cams)
    except ValueError as exc:
        parser.error(str(exc))
    if not camera_targets:
        parser.error("No active recorder camera configs found in recorder-cam*.env")

    recorder_units = tuple(f"buspcrt-recorder@{target.name}.service" for target in camera_targets)
    monitored_units = (
        DEFAULT_FIXED_MONITOR_UNITS[0],
        *recorder_units,
        *DEFAULT_FIXED_MONITOR_UNITS[1:],
    )
    journal_units = (DEFAULT_FIXED_APP_ERROR_UNITS[0], *recorder_units)

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
        monitored_units=monitored_units,
        journal_units=journal_units,
    )
