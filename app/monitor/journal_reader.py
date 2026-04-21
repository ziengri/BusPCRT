from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass

from .models import MonitorEvent, build_event_id
from .probes import parse_journal_realtime_timestamp

LOGGER = logging.getLogger(__name__)
LEVEL_RE = re.compile(r"\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|", re.IGNORECASE)
CURSOR_RE = re.compile(r"^-- cursor: (.+)$")


@dataclass
class JournalEntry:
    unit: str
    cursor: str | None
    occurred_at: str
    message: str
    raw_level: str | None
    logger_name: str | None


def read_journal_entries(
    unit: str,
    *,
    cursor: str | None,
    bootstrap_since: str,
    timeout_s: float,
) -> tuple[list[JournalEntry], str | None]:
    cmd = [
        "journalctl",
        "-u",
        unit,
        "-o",
        "json",
        "--no-pager",
        "--show-cursor",
    ]
    if cursor:
        cmd.extend(["--after-cursor", cursor])
    else:
        cmd.extend(["--since", bootstrap_since])

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("journalctl failed for %s: %s", unit, exc)
        return [], cursor

    entries: list[JournalEntry] = []
    next_cursor = cursor
    if proc.returncode not in (0,):
        if proc.returncode == 1 and not proc.stdout.strip():
            return entries, cursor
        LOGGER.warning("journalctl exited with code %s for %s", proc.returncode, unit)
        return entries, cursor

    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cursor_match = CURSOR_RE.match(line)
        if cursor_match:
            next_cursor = cursor_match.group(1)
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        entry_cursor = payload.get("__CURSOR")
        if isinstance(entry_cursor, str) and entry_cursor:
            next_cursor = entry_cursor

        message = str(payload.get("MESSAGE", ""))
        logger_name = payload.get("SYSLOG_IDENTIFIER") or payload.get("_COMM")
        if logger_name is not None:
            logger_name = str(logger_name)
        entries.append(
            JournalEntry(
                unit=unit,
                cursor=str(entry_cursor) if entry_cursor else None,
                occurred_at=parse_journal_realtime_timestamp(payload.get("__REALTIME_TIMESTAMP")),
                message=message,
                raw_level=parse_message_level(message),
                logger_name=logger_name,
            )
        )
    return entries, next_cursor


def parse_message_level(message: str) -> str | None:
    match = LEVEL_RE.search(message)
    if not match:
        return None
    return match.group(1).upper()


def first_meaningful_line(message: str) -> str:
    for raw_line in message.splitlines():
        line = raw_line.strip()
        if line:
            return line
    return message.strip()


def normalize_error_message(message: str) -> str:
    first_line = first_meaningful_line(message)
    return re.sub(r"\s+", " ", first_line).strip().lower()


def build_app_error_event(
    bus_id: str,
    entry: JournalEntry,
) -> tuple[MonitorEvent | None, str | None]:
    raw_level = (entry.raw_level or "").upper()
    if raw_level not in {"ERROR", "CRITICAL"}:
        return None, None

    normalized = normalize_error_message(entry.message)
    if not normalized:
        return None, None

    severity = "critical" if raw_level == "CRITICAL" else "error"
    message = first_meaningful_line(entry.message)
    details = {
        "logger": entry.logger_name,
        "unit": entry.unit,
        "cursor": entry.cursor,
        "rawLevel": raw_level,
    }
    event = MonitorEvent(
        event_id=build_event_id(
            bus_id=bus_id,
            kind="app.error",
            component=f"app:{entry.unit}",
            occurred_at=entry.occurred_at,
            message=message,
            details=details,
        ),
        occurred_at=entry.occurred_at,
        kind="app.error",
        component=f"app:{entry.unit}",
        severity=severity,
        message=message,
        details=details,
    )
    return event, normalized
