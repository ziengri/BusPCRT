from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

REQUIRED_RECORDER_KEYS = ("CAMERA_ID", "SOURCE", "DOOR_CHANNEL")
SUPPORTED_NUMBER_CAMS = (3, 4)


@dataclass(frozen=True)
class RecorderConfig:
    camera_id: str
    source: str
    door_channel: int
    env_path: Path
    source_host: str

    @property
    def unit_name(self) -> str:
        return f"buspcrt-recorder@{self.camera_id}.service"


def _load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        key: str(value).strip()
        for key, value in dotenv_values(path).items()
        if value not in (None, "")
    }


def _numeric_suffix(value: str) -> int | None:
    match = re.search(r"(\d+)$", value)
    if match:
        return int(match.group(1))
    return None


def camera_sort_key(camera_id: str) -> tuple[int, int, str]:
    numeric = _numeric_suffix(camera_id)
    if numeric is not None:
        return (0, numeric, camera_id.lower())
    return (1, 0, camera_id.lower())


def camera_numeric_id(camera_id: str, fallback: int) -> int:
    numeric = _numeric_suffix(camera_id)
    if numeric is not None:
        return numeric
    return int(fallback)


def parse_number_cams(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NUMBER_CAMS must be 3 or 4, got: {value}") from exc
    if parsed not in SUPPORTED_NUMBER_CAMS:
        raise ValueError(f"NUMBER_CAMS must be 3 or 4, got: {parsed}")
    return parsed


def _parse_recorder_config(env_path: Path, raw: dict[str, str] | None = None) -> RecorderConfig | None:
    raw = raw if raw is not None else _load_env(env_path)
    present_keys = [key for key in REQUIRED_RECORDER_KEYS if raw.get(key)]
    if not present_keys:
        return None

    missing_keys = [key for key in REQUIRED_RECORDER_KEYS if not raw.get(key)]
    if missing_keys:
        raise ValueError(f"Recorder env {env_path} is missing required keys: {', '.join(missing_keys)}")

    camera_id = str(raw["CAMERA_ID"]).strip()
    source = str(raw["SOURCE"]).strip()
    if not camera_id:
        raise ValueError(f"Recorder env {env_path} has empty CAMERA_ID")
    if not source:
        raise ValueError(f"Recorder env {env_path} has empty SOURCE")

    try:
        door_channel = int(str(raw["DOOR_CHANNEL"]).strip())
    except ValueError as exc:
        raise ValueError(f"Recorder env {env_path} has invalid DOOR_CHANNEL") from exc

    source_host = urlsplit(source).hostname
    if not source_host:
        raise ValueError(f"Recorder env {env_path} has SOURCE without RTSP host: {source}")

    return RecorderConfig(
        camera_id=camera_id,
        source=source,
        door_channel=door_channel,
        env_path=env_path.resolve(),
        source_host=source_host,
    )


def discover_recorder_configs(project_root: Path, *, number_cams: int | None = None) -> tuple[RecorderConfig, ...]:
    number_cams = parse_number_cams(number_cams)
    configs: list[RecorderConfig] = []
    seen_camera_ids: set[str] = set()

    for env_path in sorted(project_root.glob("recorder-cam*.env"), key=lambda item: item.name.lower()):
        raw = _load_env(env_path)
        if number_cams is not None and raw.get("CAMERA_ID"):
            camera_number = _numeric_suffix(str(raw["CAMERA_ID"]).strip())
            if camera_number is None:
                raise ValueError(f"Cannot apply NUMBER_CAMS to non-numeric CAMERA_ID: {raw['CAMERA_ID']}")
            if camera_number > number_cams:
                continue

        config = _parse_recorder_config(env_path, raw)
        if config is None:
            continue
        camera_number = _numeric_suffix(config.camera_id)
        if number_cams is not None:
            if camera_number is None:
                raise ValueError(f"Cannot apply NUMBER_CAMS to non-numeric CAMERA_ID: {config.camera_id}")
            if camera_number > number_cams:
                continue
        if config.camera_id in seen_camera_ids:
            raise ValueError(f"Duplicate CAMERA_ID detected: {config.camera_id}")
        seen_camera_ids.add(config.camera_id)
        configs.append(config)

    return tuple(sorted(configs, key=lambda item: camera_sort_key(item.camera_id)))
