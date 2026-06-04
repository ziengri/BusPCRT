from __future__ import annotations

from door_gateway.protocol import DoorTelemetry
from door_gateway.state import DoorStateStore


def test_state_flags_and_snapshot() -> None:
    store = DoorStateStore()
    snap = store.update_from_doors(
        {
            1: DoorTelemetry(state=0, voltage=0x80),
            2: DoorTelemetry(state=1, voltage=0xAF),
            3: DoorTelemetry(state=0, voltage=0x93),
        },
        ts=100.0,
    )
    assert snap.any_open is True
    assert snap.all_closed is False
    assert snap.stale is False
    assert snap.doors[2].voltage == 0xAF

    snap2 = store.update_from_doors(
        {
            1: DoorTelemetry(state=0, voltage=0x80),
            2: DoorTelemetry(state=0, voltage=0xAF),
            3: DoorTelemetry(state=0, voltage=0x93),
        },
        ts=101.0,
    )
    assert snap2.any_open is False
    assert snap2.all_closed is True
    assert snap2.stale is False


def test_stale_transition_and_recovery() -> None:
    store = DoorStateStore()
    store.update_from_doors(
        {
            1: DoorTelemetry(state=0, voltage=0x00),
            2: DoorTelemetry(state=0, voltage=0x00),
            3: DoorTelemetry(state=0, voltage=0x00),
        },
        ts=10.0,
    )
    changed = store.mark_stale_if_needed(now=12.5, stale_timeout_sec=2.0)
    assert changed is True
    assert store.stale is True

    snap = store.update_from_doors(
        {
            1: DoorTelemetry(state=1, voltage=0xAF),
            2: DoorTelemetry(state=0, voltage=0x00),
            3: DoorTelemetry(state=0, voltage=0x00),
        },
        ts=13.0,
    )
    assert snap.stale is False


def test_state_supports_four_doors() -> None:
    store = DoorStateStore(door_count=4)

    snap = store.update_from_doors(
        {
            1: DoorTelemetry(state=0, voltage=0x10),
            2: DoorTelemetry(state=0, voltage=0x20),
            3: DoorTelemetry(state=0, voltage=0x30),
            4: DoorTelemetry(state=1, voltage=0x7E),
        },
        ts=42.0,
    )

    assert snap.doors[4].state == 1
    assert snap.doors[4].voltage == 0x7E
    assert snap.any_open is True
    assert snap.all_closed is False
