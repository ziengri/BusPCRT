from .camera_discovery import (
    RecorderConfig,
    camera_numeric_id,
    camera_sort_key,
    discover_recorder_configs,
    parse_number_cams,
)

__all__ = [
    "RecorderConfig",
    "camera_numeric_id",
    "camera_sort_key",
    "discover_recorder_configs",
    "parse_number_cams",
    "SessionDirs",
    "CountResult",
    "ProcessedResult",
]


def __getattr__(name: str):
    if name == "SessionDirs":
        from .session_storage import SessionDirs

        return SessionDirs
    if name in {"CountResult", "ProcessedResult"}:
        from .types import CountResult, ProcessedResult

        return {"CountResult": CountResult, "ProcessedResult": ProcessedResult}[name]
    raise AttributeError(name)
