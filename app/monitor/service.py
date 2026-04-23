from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .client import MonitorApiClient
from .config import MonitorConfig
from .journal_reader import build_app_error_event, read_journal_entries
from .models import MonitorEvent, build_event_id, isoformat_utc, utc_now
from .outbox import MonitorOutbox
from .probes import (
    compute_storage_status,
    count_timeline_pending,
    probe_camera,
    probe_connectivity,
    probe_services,
)

LOGGER = logging.getLogger(__name__)


class MonitorService:
    def __init__(
        self,
        config: MonitorConfig,
        *,
        outbox: MonitorOutbox | None = None,
        api_client: MonitorApiClient | None = None,
    ):
        self.config = config
        self.outbox = outbox or MonitorOutbox(config.monitor_db_path)
        self.api_client = api_client or MonitorApiClient(
            api_base_url=config.api_base_url,
            x_auth=config.api_x_auth,
            timeout_s=config.api_timeout_sec,
        )

    @staticmethod
    def _state_key(*parts: str) -> str:
        return ":".join(parts)

    def _get_bool_state(self, key: str) -> bool | None:
        value = self.outbox.get_state(key)
        if value is None:
            return None
        if value == "1":
            return True
        if value == "0":
            return False
        return None

    def _set_bool_state(self, key: str, value: bool) -> None:
        self.outbox.set_state(key, "1" if value else "0")

    def _next_reported_at(self) -> str:
        now = utc_now().replace(microsecond=0)
        stored = self.outbox.get_state(self._state_key("reported_at"))
        if stored:
            try:
                previous = datetime.fromisoformat(stored.replace("Z", "+00:00")).astimezone(timezone.utc)
                now = max(now, previous + timedelta(seconds=1))
            except ValueError:
                pass
        reported_at = isoformat_utc(now)
        self.outbox.set_state(self._state_key("reported_at"), reported_at)
        return reported_at

    def _camera_statuses(self, checked_at: str) -> list[dict[str, Any]]:
        camera_statuses = []
        for target in self.config.camera_targets:
            last_online_key = self._state_key("camera", str(target.camera_id), "last_online_at")
            status = probe_camera(
                target,
                timeout_s=self.config.api_timeout_sec,
                checked_at=checked_at,
                last_online_at=self.outbox.get_state(last_online_key),
            )
            if status.last_online_at is not None:
                self.outbox.set_state(last_online_key, status.last_online_at)
            camera_statuses.append(status.to_dict())
        return camera_statuses

    def _connectivity_status(self, checked_at: str) -> dict[str, Any]:
        last_online_key = self._state_key("internet", "last_online_at")
        status = probe_connectivity(
            self.api_client,
            checked_at=checked_at,
            last_online_at=self.outbox.get_state(last_online_key),
        )
        if status.api_last_online_at is not None:
            self.outbox.set_state(last_online_key, status.api_last_online_at)
        return status.to_dict()

    def _service_statuses(self, checked_at: str) -> list[dict[str, Any]]:
        return [
            status.to_dict()
            for status in probe_services(
                self.config.monitored_units,
                timeout_s=self.config.api_timeout_sec,
                checked_at=checked_at,
            )
        ]

    def _storage_status(self) -> dict[str, Any]:
        return compute_storage_status(
            self.config.sessions_dir,
            warn_pct=self.config.storage_warn_pct,
            crit_pct=self.config.storage_crit_pct,
        ).to_dict()

    def _buffer_counts(self) -> dict[str, int]:
        return {
            "monitorPendingEvents": self.outbox.count_pending_events(),
            "monitorPendingStatus": self.outbox.count_pending_status(),
            "timelinePendingRecords": count_timeline_pending(self.config.timeline_outbox_db),
        }

    def _make_event(
        self,
        *,
        occurred_at: str,
        kind: str,
        component: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> MonitorEvent:
        return MonitorEvent(
            event_id=build_event_id(
                bus_id=self.config.bus_id,
                kind=kind,
                component=component,
                occurred_at=occurred_at,
                message=message,
                details=details,
            ),
            occurred_at=occurred_at,
            kind=kind,
            component=component,
            severity=severity.lower(),
            message=message,
            details=details,
        )

    def _camera_transition_events(
        self,
        cameras: list[dict[str, Any]],
        *,
        occurred_at: str,
    ) -> list[MonitorEvent]:
        events: list[MonitorEvent] = []
        for camera in cameras:
            camera_id = int(camera["cameraId"])
            key = self._state_key("camera", str(camera_id), "reachable")
            previous = self._get_bool_state(key)
            current = bool(camera["reachable"])
            if previous is not None and previous != current:
                severity = "warning" if not current else "info"
                message = (
                    f"Camera {camera_id} is offline"
                    if not current
                    else f"Camera {camera_id} is online"
                )
                events.append(
                    self._make_event(
                        occurred_at=occurred_at,
                        kind="camera.status_changed",
                        component=f"camera-{camera_id}",
                        severity=severity,
                        message=message,
                        details={
                            "reachable": current,
                            "ip": camera.get("ip"),
                            "source": camera.get("source"),
                        },
                    )
                )
            self._set_bool_state(key, current)
        return events

    def _internet_transition_events(
        self,
        connectivity: dict[str, Any],
        *,
        occurred_at: str,
    ) -> list[MonitorEvent]:
        key = self._state_key("internet", "reachable")
        previous = self._get_bool_state(key)
        current = bool(connectivity["apiReachable"])
        events: list[MonitorEvent] = []
        if previous is not None and previous != current:
            message = "API connectivity is offline" if not current else "API connectivity restored"
            events.append(
                self._make_event(
                    occurred_at=occurred_at,
                    kind="internet.status_changed",
                    component="internet",
                    severity="warning" if not current else "info",
                    message=message,
                    details={"apiReachable": current},
                )
            )
        self._set_bool_state(key, current)
        return events

    def _service_transition_events(
        self,
        services: list[dict[str, Any]],
        *,
        occurred_at: str,
    ) -> list[MonitorEvent]:
        events: list[MonitorEvent] = []
        for service in services:
            name = str(service["name"])
            current = str(service.get("monitorState", "error"))
            key = self._state_key("service", name, "monitor_state")
            previous = self.outbox.get_state(key)
            if previous is not None and previous != current:
                is_error = current != "ok"
                message = (
                    f"Service {name} is unhealthy"
                    if is_error
                    else f"Service {name} recovered"
                )
                events.append(
                    self._make_event(
                        occurred_at=occurred_at,
                        kind="service.status_changed",
                        component=f"service:{name}",
                        severity="error" if is_error else "info",
                        message=message,
                        details={
                            "status": service.get("status"),
                            "subState": service.get("subState"),
                            "result": service.get("result"),
                            "execMainStatus": service.get("execMainStatus"),
                            "monitorState": current,
                        },
                    )
                )
            self.outbox.set_state(key, current)
        return events

    def _storage_transition_events(
        self,
        storage: dict[str, Any],
        *,
        occurred_at: str,
    ) -> list[MonitorEvent]:
        key = self._state_key("storage", "threshold")
        previous = self.outbox.get_state(key)
        current = str(storage.get("threshold", "normal"))
        events: list[MonitorEvent] = []
        if previous is not None and previous != current:
            if current == "normal":
                severity = "info"
                message = "Storage usage recovered below warning threshold"
            elif current == "warning":
                severity = "warning"
                message = "Storage usage reached warning threshold"
            else:
                severity = "critical"
                message = "Storage usage reached critical threshold"
            events.append(
                self._make_event(
                    occurred_at=occurred_at,
                    kind="storage.threshold",
                    component=f"storage:{storage.get('path')}",
                    severity=severity,
                    message=message,
                    details={
                        "threshold": current,
                        "usedPercent": storage.get("usedPercent"),
                        "freeBytes": storage.get("freeBytes"),
                    },
                )
            )
        self.outbox.set_state(key, current)
        return events

    def _should_emit_app_error(self, unit: str, normalized_message: str, occurred_at: str) -> bool:
        key = self._state_key("app_error", unit, normalized_message)
        previous = self.outbox.get_state(key)
        if previous is not None:
            try:
                previous_dt = datetime.fromisoformat(previous.replace("Z", "+00:00")).astimezone(timezone.utc)
                current_dt = datetime.fromisoformat(occurred_at.replace("Z", "+00:00")).astimezone(timezone.utc)
                if (current_dt - previous_dt).total_seconds() < self.config.error_dedup_sec:
                    return False
            except ValueError:
                pass
        self.outbox.set_state(key, occurred_at)
        return True

    def _collect_app_error_events(self) -> tuple[list[MonitorEvent], dict[str, str]]:
        events: list[MonitorEvent] = []
        cursors_to_update: dict[str, str] = {}
        for unit in self.config.journal_units:
            current_cursor = self.outbox.get_cursor(unit)
            entries, next_cursor = read_journal_entries(
                unit,
                cursor=current_cursor,
                bootstrap_since=self.config.journal_bootstrap_since,
                timeout_s=self.config.api_timeout_sec,
            )
            for entry in entries:
                event, normalized_message = build_app_error_event(self.config.bus_id, entry)
                if event is None or normalized_message is None:
                    continue
                if self._should_emit_app_error(unit, normalized_message, event.occurred_at):
                    events.append(event)
            if next_cursor:
                cursors_to_update[unit] = next_cursor
        return events, cursors_to_update

    def _enqueue_events_and_cursors(
        self,
        events: list[MonitorEvent],
        cursor_updates: dict[str, str],
    ) -> None:
        self.outbox.enqueue_events(events)
        for unit, cursor in cursor_updates.items():
            self.outbox.set_cursor(unit, cursor)

    def _flush_events(self) -> None:
        while True:
            rows = self.outbox.get_due_events(self.config.event_batch_size)
            if not rows:
                return
            payloads = [json.loads(str(row["payload"])) for row in rows]
            row_ids = [int(row["id"]) for row in rows]
            try:
                self.api_client.send_events(self.config.bus_id, payloads)
            except Exception as exc:  # noqa: BLE001
                self.outbox.mark_events_failed(row_ids, str(exc))
                LOGGER.warning("Failed to flush monitor events: %s", exc)
                return
            self.outbox.mark_events_sent(row_ids)

    def _flush_status(self) -> None:
        row = self.outbox.get_pending_status()
        if row is None:
            return
        try:
            payload = json.loads(str(row["payload"]))
            self.api_client.send_status(payload)
        except Exception as exc:  # noqa: BLE001
            self.outbox.mark_status_failed(str(exc))
            LOGGER.warning("Failed to flush device status: %s", exc)
            return
        self.outbox.clear_pending_status()

    def _build_status_snapshot(
        self,
        *,
        reported_at: str,
        connectivity: dict[str, Any],
        cameras: list[dict[str, Any]],
        services: list[dict[str, Any]],
        storage: dict[str, Any],
        buffers: dict[str, int],
    ) -> dict[str, Any]:
        return {
            "bus": self.config.bus_id,
            "reportedAt": reported_at,
            "connectivity": connectivity,
            "cameras": cameras,
            "services": services,
            "storage": storage,
            "buffers": buffers,
        }

    def run_once(self) -> None:
        reported_at = self._next_reported_at()
        cameras = self._camera_statuses(reported_at)
        connectivity = self._connectivity_status(reported_at)
        services = self._service_statuses(reported_at)
        storage = self._storage_status()

        transition_events: list[MonitorEvent] = []
        transition_events.extend(self._camera_transition_events(cameras, occurred_at=reported_at))
        transition_events.extend(self._internet_transition_events(connectivity, occurred_at=reported_at))
        transition_events.extend(self._service_transition_events(services, occurred_at=reported_at))
        transition_events.extend(self._storage_transition_events(storage, occurred_at=reported_at))

        journal_events, cursor_updates = self._collect_app_error_events()
        all_events = [*transition_events, *journal_events]
        self._enqueue_events_and_cursors(all_events, cursor_updates)

        initial_buffers = self._buffer_counts()
        self.outbox.set_pending_status(
            self._build_status_snapshot(
                reported_at=reported_at,
                connectivity=connectivity,
                cameras=cameras,
                services=services,
                storage=storage,
                buffers=initial_buffers,
            ),
            reported_at,
        )

        self._flush_events()
        final_buffers = self._buffer_counts()
        self.outbox.set_pending_status(
            self._build_status_snapshot(
                reported_at=reported_at,
                connectivity=connectivity,
                cameras=cameras,
                services=services,
                storage=storage,
                buffers=final_buffers,
            ),
            reported_at,
        )
        self.outbox.set_last_status(
            self._build_status_snapshot(
                reported_at=reported_at,
                connectivity=connectivity,
                cameras=cameras,
                services=services,
                storage=storage,
                buffers=final_buffers,
            ),
            reported_at,
        )
        self._flush_status()

    def run_forever(self) -> None:
        LOGGER.info("Starting onboard monitor for bus %s", self.config.bus_id)
        while True:
            started_at = time.monotonic()
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Monitor loop error")

            elapsed = time.monotonic() - started_at
            sleep_for = max(0.0, self.config.interval_sec - elapsed)
            time.sleep(sleep_for)
