from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Snapshot:
    seq: int
    ts: float
    doors: dict[int, int]
    any_open: bool
    all_closed: bool
    stale: bool


class DoorStateStore:
    def __init__(self) -> None:
        self.last_doors_state: dict[int, int] = {1: 0, 2: 0, 3: 0}
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
        self.last_doors_state = {1: int(doors[1]), 2: int(doors[2]), 3: int(doors[3])}
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
