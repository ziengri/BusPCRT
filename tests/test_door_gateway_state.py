from __future__ import annotations

from door_gateway.state import DoorStateStore


def test_state_flags_and_snapshot() -> None:
    store = DoorStateStore()
    snap = store.update_from_doors({1: 0, 2: 1, 3: 0}, ts=100.0)
    assert snap.any_open is True
    assert snap.all_closed is False
    assert snap.stale is False

    snap2 = store.update_from_doors({1: 0, 2: 0, 3: 0}, ts=101.0)
    assert snap2.any_open is False
    assert snap2.all_closed is True
    assert snap2.stale is False


def test_stale_transition_and_recovery() -> None:
    store = DoorStateStore()
    store.update_from_doors({1: 0, 2: 0, 3: 0}, ts=10.0)
    changed = store.mark_stale_if_needed(now=12.5, stale_timeout_sec=2.0)
    assert changed is True
    assert store.stale is True

    snap = store.update_from_doors({1: 1, 2: 0, 3: 0}, ts=13.0)
    assert snap.stale is False
