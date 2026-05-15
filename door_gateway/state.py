from __future__ import annotations

from dataclasses import dataclass

from .protocol import configured_door_ids


@dataclass
class Snapshot:
    seq: int
    ts: float
    doors: dict[int, int]
    any_open: bool
    all_closed: bool
    stale: bool


class DoorStateStore:
    def __init__(self, door_count: int = 3) -> None:
        self.door_ids = configured_door_ids(door_count)
        self.last_doors_state: dict[int, int] = {door_id: 0 for door_id in self.door_ids}
        self.last_packet_ts: float | None = None
        self.seq: int = 0
        self.stale: bool = True

    @staticmethod
    def _flags(doors: dict[int, int]) -> tuple[bool, bool]:
        any_open = any(v == 1 for v in doors.values())
        all_closed = all(v == 0 for v in doors.values())
        return any_open, all_closed

    def snapshot(self, ts: float) -> Snapshot:
        any_open, all_closed = self._flags(self.last_doors_state)
        return Snapshot(
            seq=self.seq,
            ts=ts,
            doors=dict(self.last_doors_state),
            any_open=any_open,
            all_closed=all_closed,
            stale=self.stale,
        )

    def update_from_doors(self, doors: dict[int, int], ts: float) -> Snapshot:
        self.last_doors_state = {door_id: int(doors[door_id]) for door_id in self.door_ids}
        self.last_packet_ts = ts
        self.stale = False
        self.seq += 1
        return self.snapshot(ts)

    def mark_stale_if_needed(self, now: float, stale_timeout_sec: float) -> bool:
        if self.last_packet_ts is None:
            return False
        if self.stale:
            return False
        if now - self.last_packet_ts > stale_timeout_sec:
            self.stale = True
            self.seq += 1
            return True
        return False
