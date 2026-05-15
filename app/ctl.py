from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from dotenv import dotenv_values

from app.monitor.outbox import MonitorOutbox
from app.monitor.probes import parse_systemctl_show
from app.shared import RecorderConfig, discover_recorder_configs, parse_number_cams

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVICE_ENV_PATH = Path("/etc/pcrt/device.env")
CONFIG_ENV_PATH = PROJECT_ROOT / "config.env"
MONITOR_ENV_PATH = PROJECT_ROOT / "monitor.env"
DEFAULT_MONITOR_DB_PATH = Path("/var/lib/pcrt/monitor.sqlite")
DEFAULT_MANUAL_CAPTURES_DIR = Path("/var/lib/pcrt/manual-captures")
DOOR_GATEWAY_ENV_PATH = PROJECT_ROOT / "door_gateway.env"
UNIT_SHOW_PROPERTIES = (
    "Description",
    "LoadState",
    "ActiveState",
    "SubState",
    "UnitFileState",
    "Result",
    "ExecMainStatus",
    "ActiveEnterTimestamp",
)
FIXED_SERVICE_TARGETS: dict[str, str] = {
    "processor": "buspcrt-processor.service",
    "monitor": "buspcrt-monitor.service",
    "door": "buspcrt-door-gateway.service",
    "updater": "buspcrt-updater.service",
    "updater-timer": "buspcrt-updater.timer",
    "cleanup": "buspcrt-sessions-cleanup.service",
}
FIXED_CORE_SERVICE_ALIASES = ("processor", "monitor", "door", "updater-timer")
CAMERA_GROUP_ALIAS = "cams"


class CtlError(RuntimeError):
    pass


@dataclass
class RuntimeConfig:
    project_root: Path
    config_env_path: Path
    device_env_path: Path
    monitor_env_path: Path
    door_gateway_env_path: Path
    bus_id: str | None
    monitor_interval_sec: float
    monitor_db_path: Path
    zmq_ipc_endpoint: str
    number_cams: int | None
    door_count: int
    recorder_configs: tuple[RecorderConfig, ...]


@dataclass
class UnitStatus:
    alias: str | None
    unit: str
    installed: bool
    active: bool
    description: str | None
    load_state: str | None
    active_state: str | None
    sub_state: str | None
    unit_file_state: str | None
    result: str | None
    exec_main_status: int | None
    active_enter_timestamp: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "unit": self.unit,
            "installed": self.installed,
            "active": self.active,
            "description": self.description,
            "loadState": self.load_state,
            "activeState": self.active_state,
            "subState": self.sub_state,
            "unitFileState": self.unit_file_state,
            "result": self.result,
            "execMainStatus": self.exec_main_status,
            "activeEnterTimestamp": self.active_enter_timestamp,
        }


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        key: str(value)
        for key, value in dotenv_values(path).items()
        if value not in (None, "")
    }


def _resolve_path(value: str | None, base_dir: Path, default: Path) -> Path:
    if value:
        path = Path(value)
    else:
        path = default
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    config_env_path = Path(args.config_env_file).resolve()
    project_root = config_env_path.parent
    monitor_env_path = Path(args.monitor_env_file).resolve()
    device_env_path = Path(args.device_env_file).resolve()
    door_gateway_env_path = (project_root / "door_gateway.env").resolve()

    config_raw = _load_env_file(config_env_path)
    monitor_raw = _load_env_file(monitor_env_path)
    device_raw = _load_env_file(device_env_path)
    door_gateway_raw = _load_env_file(door_gateway_env_path)

    monitor_db_path = _resolve_path(
        monitor_raw.get("MONITOR_DB_PATH"),
        project_root,
        DEFAULT_MONITOR_DB_PATH,
    )
    interval_raw = monitor_raw.get("MONITOR_INTERVAL_SEC", "30")
    try:
        monitor_interval_sec = float(interval_raw)
    except ValueError:
        monitor_interval_sec = 30.0
    try:
        number_cams = parse_number_cams(device_raw.get("NUMBER_CAMS"))
        recorder_configs = discover_recorder_configs(project_root, number_cams=number_cams)
    except ValueError as exc:
        raise CtlError(str(exc)) from exc

    door_count_raw = door_gateway_raw.get("DOOR_COUNT") or number_cams or "3"
    try:
        door_count = int(door_count_raw)
    except ValueError as exc:
        raise CtlError(f"Invalid DOOR_COUNT in {door_gateway_env_path}: {door_count_raw}") from exc
    if door_count not in (3, 4):
        raise CtlError(f"Unsupported DOOR_COUNT in {door_gateway_env_path}: {door_count}")

    return RuntimeConfig(
        project_root=project_root,
        config_env_path=config_env_path,
        device_env_path=device_env_path,
        monitor_env_path=monitor_env_path,
        door_gateway_env_path=door_gateway_env_path,
        bus_id=device_raw.get("BUS_ID"),
        monitor_interval_sec=monitor_interval_sec,
        monitor_db_path=monitor_db_path,
        zmq_ipc_endpoint=config_raw.get("ZMQ_IPC_ENDPOINT", "ipc:///run/doors.sock"),
        number_cams=number_cams,
        door_count=door_count,
        recorder_configs=recorder_configs,
    )


def build_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(prog="pcrt", description="BusPCRT onboard operations CLI")
    parser.add_argument("--config-env-file", default=str(CONFIG_ENV_PATH))
    parser.add_argument("--monitor-env-file", default=str(MONITOR_ENV_PATH))
    parser.add_argument("--device-env-file", default=str(DEVICE_ENV_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)
    command_parsers: dict[str, argparse.ArgumentParser] = {}

    summary = subparsers.add_parser("summary", help="Show board summary", description="Show board summary")
    summary.add_argument("--json", action="store_true", dest="as_json")
    command_parsers["summary"] = summary

    list_parser = subparsers.add_parser("list", help="List known targets", description="List known targets")
    list_parser.add_argument("--json", action="store_true", dest="as_json")
    command_parsers["list"] = list_parser

    status = subparsers.add_parser("status", help="Show unit status", description="Show unit status")
    status.add_argument("targets", nargs="+")
    status.add_argument("--json", action="store_true", dest="as_json")
    command_parsers["status"] = status

    logs = subparsers.add_parser("logs", help="Show unit logs", description="Show unit logs")
    logs.add_argument("target")
    logs.add_argument("-n", type=int, default=100)
    logs.add_argument("-f", "--follow", action="store_true")
    command_parsers["logs"] = logs

    for name in ("start", "stop", "restart"):
        cmd = subparsers.add_parser(
            name,
            help=f"{name.title()} service units",
            description=f"{name.title()} service units",
        )
        cmd.add_argument("targets", nargs="+")
        command_parsers[name] = cmd

    doors = subparsers.add_parser("doors", help="Door tools", description="Door tools")
    doors_sub = doors.add_subparsers(dest="doors_command", required=True)
    doors_live = doors_sub.add_parser(
        "live",
        help="Run interactive door simulator",
        description="Run interactive door simulator",
    )
    doors_live.add_argument("--endpoint", default=None)
    command_parsers["doors"] = doors

    record = subparsers.add_parser(
        "record",
        help="Manual camera recording",
        description="Manual camera recording",
    )
    record.add_argument("camera")
    record.add_argument("--duration", type=float, default=None)
    record.add_argument("--output-dir", default=None)
    command_parsers["record"] = record

    help_parser = subparsers.add_parser("help", help="Show command help", description="Show command help")
    help_parser.add_argument("topic", nargs="?", choices=sorted(command_parsers.keys()))
    command_parsers["help"] = help_parser

    return parser, command_parsers


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _camera_aliases(runtime: RuntimeConfig) -> tuple[str, ...]:
    return tuple(config.camera_id for config in runtime.recorder_configs)


def _service_targets(runtime: RuntimeConfig) -> dict[str, str]:
    targets = dict(FIXED_SERVICE_TARGETS)
    for config in runtime.recorder_configs:
        targets[config.camera_id] = config.unit_name
    return targets


def _core_service_aliases(runtime: RuntimeConfig) -> tuple[str, ...]:
    return (
        FIXED_CORE_SERVICE_ALIASES[0],
        FIXED_CORE_SERVICE_ALIASES[1],
        FIXED_CORE_SERVICE_ALIASES[2],
        *_camera_aliases(runtime),
        FIXED_CORE_SERVICE_ALIASES[3],
    )


def _group_targets(runtime: RuntimeConfig) -> dict[str, tuple[str, ...]]:
    camera_aliases = _camera_aliases(runtime)
    if not camera_aliases:
        return {}
    return {CAMERA_GROUP_ALIAS: camera_aliases}


def _recorder_env_by_alias(runtime: RuntimeConfig) -> dict[str, Path]:
    return {config.camera_id: config.env_path for config in runtime.recorder_configs}


def resolve_units(runtime: RuntimeConfig, targets: Sequence[str], *, allow_groups: bool) -> list[tuple[str | None, str]]:
    service_targets = _service_targets(runtime)
    group_targets = _group_targets(runtime)
    resolved: list[tuple[str | None, str]] = []
    seen_units: set[str] = set()
    for target in targets:
        if target in group_targets:
            if not allow_groups:
                raise CtlError(f"Target '{target}' is read-only and cannot be used here.")
            for alias in group_targets[target]:
                unit = service_targets[alias]
                if unit not in seen_units:
                    resolved.append((alias, unit))
                    seen_units.add(unit)
            continue

        unit = service_targets.get(target, target)
        alias = next((key for key, value in service_targets.items() if value == unit), None)
        if alias is None and not unit.endswith(".service") and not unit.endswith(".timer"):
            raise CtlError(f"Unknown target: {target}")
        if unit not in seen_units:
            resolved.append((alias, unit))
            seen_units.add(unit)
    return resolved


def unit_exists(unit: str) -> bool:
    proc = subprocess.run(
        ["systemctl", "list-unit-files", unit, "--no-legend", "--no-pager"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.split()[0] == unit:
            return True
    return False


def _unit_installed_from_show(unit: str, parsed: dict[str, str]) -> bool:
    load_state = (parsed.get("LoadState") or "").strip()
    if load_state and load_state != "not-found":
        return True

    if unit_exists(unit):
        return True

    if "@" not in unit:
        return False

    prefix, suffix = unit.split("@", 1)
    if "." not in suffix:
        return False

    _instance_name, unit_suffix = suffix.split(".", 1)
    template_unit = f"{prefix}@.{unit_suffix}"
    return unit_exists(template_unit)


def unit_status(alias: str | None, unit: str) -> UnitStatus:
    proc = subprocess.run(
        [
            "systemctl",
            "show",
            unit,
            f"--property={','.join(UNIT_SHOW_PROPERTIES)}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    parsed = parse_systemctl_show(proc.stdout)
    installed = _unit_installed_from_show(unit, parsed)
    active_state = parsed.get("ActiveState")
    return UnitStatus(
        alias=alias,
        unit=unit,
        installed=installed,
        active=active_state == "active",
        description=parsed.get("Description"),
        load_state=parsed.get("LoadState"),
        active_state=active_state,
        sub_state=parsed.get("SubState"),
        unit_file_state=parsed.get("UnitFileState"),
        result=parsed.get("Result"),
        exec_main_status=_safe_int(parsed.get("ExecMainStatus")),
        active_enter_timestamp=parsed.get("ActiveEnterTimestamp") or None,
    )


def _safe_int(value: str | None) -> int | None:
    if value in (None, "", "n/a"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _require_root(action_description: str) -> None:
    if os.geteuid() != 0:
        raise CtlError(f"{action_description} requires root. Use: sudo pcrt {action_description}")


def _stale_cutoff_seconds(interval_sec: float) -> float:
    return (2.0 * interval_sec) + 30.0


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _snapshot_stale(reported_at: str | None, interval_sec: float) -> bool | None:
    if not reported_at:
        return None
    dt = _parse_iso_utc(reported_at)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt) > timedelta(seconds=_stale_cutoff_seconds(interval_sec))


def _read_monitor_snapshot(runtime: RuntimeConfig) -> tuple[dict[str, Any] | None, bool | None]:
    if not runtime.monitor_db_path.exists():
        return None, None
    outbox = MonitorOutbox(runtime.monitor_db_path)
    snapshot = outbox.get_last_status()
    if snapshot is None:
        pending_row = outbox.get_pending_status()
        if pending_row is not None:
            try:
                pending = json.loads(str(pending_row["payload"]))
                if isinstance(pending, dict):
                    snapshot = pending
            except json.JSONDecodeError:
                snapshot = None
    if snapshot is None:
        return None, None
    return snapshot, _snapshot_stale(snapshot.get("reportedAt"), runtime.monitor_interval_sec)


def _health_verdict(
    runtime: RuntimeConfig,
    statuses: dict[str, UnitStatus],
    snapshot: dict[str, Any] | None,
    stale: bool | None,
) -> str:
    for alias in _core_service_aliases(runtime):
        status = statuses[alias]
        if not status.installed or not status.active:
            return "error"

    if snapshot is None:
        return "degraded" if statuses["monitor"].active else "error"
    if stale:
        return "degraded"

    connectivity = snapshot.get("connectivity") if isinstance(snapshot.get("connectivity"), dict) else {}
    if connectivity.get("apiReachable") is False:
        return "degraded"
    cameras = snapshot.get("cameras")
    if isinstance(cameras, list):
        for camera in cameras:
            if isinstance(camera, dict) and camera.get("reachable") is False:
                return "degraded"
    return "ok"


def build_summary(runtime: RuntimeConfig) -> dict[str, Any]:
    service_targets = _service_targets(runtime)
    service_statuses = {
        alias: unit_status(alias, unit)
        for alias, unit in service_targets.items()
    }
    snapshot, stale = _read_monitor_snapshot(runtime)
    verdict = _health_verdict(runtime, service_statuses, snapshot, stale)
    return {
        "busId": runtime.bus_id,
        "health": verdict,
        "monitorSnapshot": snapshot,
        "monitorSnapshotStale": stale,
        "services": {alias: status.to_dict() for alias, status in service_statuses.items()},
        "coreServiceAliases": list(_core_service_aliases(runtime)),
    }


def render_summary(summary: dict[str, Any]) -> None:
    print(f"BUS_ID: {summary.get('busId') or 'unknown'}")
    print(f"Health: {summary['health']}")
    stale = summary.get("monitorSnapshotStale")
    stale_text = "unknown" if stale is None else ("yes" if stale else "no")
    print(f"Monitor snapshot stale: {stale_text}")

    print("")
    print("Core services:")
    for alias in summary.get("coreServiceAliases", []):
        item = summary["services"][alias]
        status_text = "active" if item["active"] else (item.get("activeState") or "unknown")
        installed = "installed" if item["installed"] else "missing"
        print(f"  {alias:13} {status_text:10} {installed}")

    snapshot = summary.get("monitorSnapshot")
    if not isinstance(snapshot, dict):
        print("")
        print("Monitoring: unknown")
        return

    connectivity = snapshot.get("connectivity") if isinstance(snapshot.get("connectivity"), dict) else {}
    print("")
    print("Monitoring:")
    print(f"  reportedAt: {snapshot.get('reportedAt', 'unknown')}")
    print(f"  apiReachable: {connectivity.get('apiReachable', 'unknown')}")

    cameras = snapshot.get("cameras")
    if isinstance(cameras, list):
        for camera in cameras:
            if not isinstance(camera, dict):
                continue
            label = camera.get("name") or f"cam{camera.get('cameraId')}"
            print(f"  {label}: reachable={camera.get('reachable', 'unknown')} ip={camera.get('ip', 'unknown')}")

    storage = snapshot.get("storage")
    if isinstance(storage, dict):
        print(f"  storage: threshold={storage.get('threshold', 'unknown')} freeBytes={storage.get('freeBytes', 'unknown')}")

    buffers = snapshot.get("buffers")
    if isinstance(buffers, dict):
        print(
            "  buffers: "
            f"monitorPendingEvents={buffers.get('monitorPendingEvents', 'unknown')} "
            f"monitorPendingStatus={buffers.get('monitorPendingStatus', 'unknown')} "
            f"timelinePendingRecords={buffers.get('timelinePendingRecords', 'unknown')}"
        )


def build_list_payload(runtime: RuntimeConfig) -> list[dict[str, Any]]:
    service_targets = _service_targets(runtime)
    group_targets = _group_targets(runtime)
    rows: list[dict[str, Any]] = []
    for alias, unit in service_targets.items():
        status = unit_status(alias, unit)
        rows.append(
            {
                "alias": alias,
                "kind": "unit",
                "unit": unit,
                "installed": status.installed,
                "active": status.active,
            }
        )

    for alias, targets in group_targets.items():
        target_statuses = [unit_status(target_alias, service_targets[target_alias]) for target_alias in targets]
        rows.append(
            {
                "alias": alias,
                "kind": "group",
                "targets": list(targets),
                "installedCount": sum(1 for status in target_statuses if status.installed),
                "activeCount": sum(1 for status in target_statuses if status.active),
            }
            )
    return rows


def render_list(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row["kind"] == "unit":
            print(
                f"{row['alias']:13} {row['unit']:40} "
                f"installed={'yes' if row['installed'] else 'no':3} "
                f"active={'yes' if row['active'] else 'no'}"
            )
        else:
            print(
                f"{row['alias']:13} group({', '.join(row['targets'])}) "
                f"installed={row['installedCount']}/{len(row['targets'])} "
                f"active={row['activeCount']}/{len(row['targets'])}"
            )


def build_status_payload(runtime: RuntimeConfig, targets: Sequence[str]) -> list[dict[str, Any]]:
    return [unit_status(alias, unit).to_dict() for alias, unit in resolve_units(runtime, targets, allow_groups=True)]


def render_status(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        if index:
            print("")
        print(f"{row.get('alias') or row['unit']}:")
        print(f"  unit: {row['unit']}")
        print(f"  installed: {row['installed']}")
        print(f"  active: {row['active']}")
        print(f"  activeState: {row.get('activeState')}")
        print(f"  subState: {row.get('subState')}")
        print(f"  result: {row.get('result')}")


def run_logs(runtime: RuntimeConfig, target: str, *, lines: int, follow: bool) -> int:
    resolved = resolve_units(runtime, [target], allow_groups=True)
    units = [unit for _alias, unit in resolved]
    cmd = ["journalctl"]
    for unit in units:
        cmd.extend(["-u", unit])
    cmd.extend(["-n", str(max(1, int(lines))), "--no-pager"])
    if follow:
        cmd.append("-f")
    return subprocess.run(cmd, check=False).returncode


def run_systemctl_action(action: str, units: Sequence[str]) -> None:
    _require_root(action)
    cmd = ["systemctl", action, *units]
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise CtlError(f"systemctl {action} failed for: {', '.join(units)}")


def _was_active(unit: str) -> bool:
    proc = subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False)
    return proc.returncode == 0


@contextlib.contextmanager
def maybe_stopped_unit(unit: str, *, action_label: str):
    was_active = _was_active(unit)
    if was_active:
        _require_root(action_label)
        run_systemctl_action("stop", [unit])
    try:
        yield was_active
    finally:
        if was_active:
            run_systemctl_action("start", [unit])


def _resolve_recorder_env_path(runtime: RuntimeConfig, camera_alias: str) -> Path:
    env_by_alias = _recorder_env_by_alias(runtime)
    env_path = env_by_alias.get(camera_alias)
    if env_path is None:
        if runtime.number_cams is not None:
            try:
                requested_number = int(camera_alias[3:] if camera_alias.startswith("cam") else camera_alias)
            except ValueError:
                requested_number = None
            if requested_number is not None and requested_number > runtime.number_cams:
                raise CtlError(f"Camera {camera_alias} is not active for NUMBER_CAMS={runtime.number_cams}")
        available = ", ".join(sorted(env_by_alias)) or "none"
        raise CtlError(f"Unknown recorder camera alias: {camera_alias}. Available cameras: {available}")
    return env_path


def _resolve_output_dir(camera_alias: str, output_dir: str | None) -> Path:
    if output_dir:
        path = Path(output_dir).expanduser()
        return path if path.is_absolute() else path.resolve()
    return DEFAULT_MANUAL_CAPTURES_DIR / camera_alias


def _manual_capture(camera_alias: str, env_path: Path, output_dir: Path, duration: float | None) -> dict[str, Any]:
    raw = _load_env_file(env_path)
    source = raw.get("SOURCE")
    camera_id = raw.get("CAMERA_ID", camera_alias)
    fps_raw = raw.get("FPS", "25")
    try:
        fps = int(fps_raw)
    except ValueError:
        fps = 25

    if not source:
        raise CtlError(f"Missing SOURCE in {env_path}")

    try:
        from app.recording.video_source import OpenCVVideoSource
        from video_session import SessionWriter
    except Exception as exc:  # noqa: BLE001
        raise CtlError(f"Failed to import video recording runtime: {exc}") from exc

    source_reader = OpenCVVideoSource(source)
    output_dir.mkdir(parents=True, exist_ok=True)

    writer = None
    first_frame_deadline = time.monotonic() + 10.0
    try:
        first_frame = None
        while time.monotonic() < first_frame_deadline:
            frame = source_reader.read()
            if frame is not None:
                first_frame = frame
                break
            time.sleep(0.1)
        if first_frame is None:
            raise CtlError(f"Failed to read first frame from {camera_alias}")

        height, width = int(first_frame.shape[0]), int(first_frame.shape[1])
        writer = SessionWriter(output_dir=output_dir, camera_id=str(camera_id), width=width, height=height, fps=fps)
        writer.write_frame(first_frame)

        started = time.monotonic()
        interrupted = False
        while True:
            if duration is not None and (time.monotonic() - started) >= duration:
                break
            try:
                frame = source_reader.read()
            except KeyboardInterrupt:
                interrupted = True
                break
            if frame is None:
                time.sleep(0.02)
                continue
            if frame.shape[0] != height or frame.shape[1] != width:
                try:
                    import cv2
                except Exception as exc:  # noqa: BLE001
                    raise CtlError(f"Failed to resize manual capture frame: {exc}") from exc
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            writer.write_frame(frame)

        meta_path = writer.close()
        return {
            "camera": camera_alias,
            "outputDir": str(output_dir),
            "metaPath": str(meta_path),
            "interrupted": interrupted,
        }
    except KeyboardInterrupt:
        if writer is not None:
            meta_path = writer.close()
            return {
                "camera": camera_alias,
                "outputDir": str(output_dir),
                "metaPath": str(meta_path),
                "interrupted": True,
            }
        raise
    finally:
        source_reader.release()


def run_record(runtime: RuntimeConfig, camera_alias: str, duration: float | None, output_dir: str | None) -> dict[str, Any]:
    env_path = _resolve_recorder_env_path(runtime, camera_alias)
    if not env_path.exists():
        raise CtlError(f"Recorder env not found for {camera_alias}: {env_path}")
    unit = _service_targets(runtime)[camera_alias]
    target_output_dir = _resolve_output_dir(camera_alias, output_dir)
    with maybe_stopped_unit(unit, action_label=f"record {camera_alias}"):
        return _manual_capture(camera_alias, env_path, target_output_dir, duration)


def run_doors_live(runtime: RuntimeConfig, endpoint_override: str | None = None) -> int:
    endpoint = endpoint_override or runtime.zmq_ipc_endpoint
    simulator = runtime.project_root / "scripts" / "door_zmq_terminal_sim.py"
    if not simulator.exists():
        raise CtlError(f"Door simulator not found: {simulator}")

    with maybe_stopped_unit(FIXED_SERVICE_TARGETS["door"], action_label="doors live"):
        proc = subprocess.run(
            [
                sys.executable,
                str(simulator),
                "--endpoint",
                endpoint,
                "--door-count",
                str(runtime.door_count),
            ],
            cwd=runtime.project_root,
            check=False,
        )
        return proc.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser, command_parsers = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.command == "help":
            target = args.topic
            if target:
                command_parsers[target].print_help()
            else:
                parser.print_help()
            return 0

        runtime = load_runtime_config(args)

        if args.command == "summary":
            payload = build_summary(runtime)
            if args.as_json:
                print_json(payload)
            else:
                render_summary(payload)
            return 0

        if args.command == "list":
            payload = build_list_payload(runtime)
            if args.as_json:
                print_json(payload)
            else:
                render_list(payload)
            return 0

        if args.command == "status":
            payload = build_status_payload(runtime, args.targets)
            if args.as_json:
                print_json(payload)
            else:
                render_status(payload)
            return 0

        if args.command == "logs":
            return run_logs(runtime, args.target, lines=args.n, follow=args.follow)

        if args.command in {"start", "stop", "restart"}:
            resolved = resolve_units(runtime, args.targets, allow_groups=False)
            run_systemctl_action(args.command, [unit for _alias, unit in resolved])
            return 0

        if args.command == "doors":
            if args.doors_command == "live":
                return run_doors_live(runtime, endpoint_override=args.endpoint)

        if args.command == "record":
            payload = run_record(runtime, args.camera, args.duration, args.output_dir)
            print_json(payload)
            return 0

        raise CtlError(f"Unsupported command: {args.command}")
    except CtlError as exc:
        print(str(exc), file=sys.stderr)
        return 2
