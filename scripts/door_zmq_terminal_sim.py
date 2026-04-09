from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from door_gateway.publisher import DoorPublisher
from door_gateway.state import DoorStateStore


def _build_raw_packet(doors: dict[int, int]) -> bytes:
    return b"!DOORS:1=" + bytes([doors[1]]) + b";2=" + bytes([doors[2]]) + b";3=" + bytes([doors[3]]) + b";"


def _hex_dump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _publish(store: DoorStateStore, publisher: DoorPublisher) -> None:
    snap = store.snapshot(time.time())
    publisher.publish_snapshot(snap)
    raw = _build_raw_packet(snap.doors)
    print(f"Published doors={snap.doors} seq={snap.seq} stale={snap.stale}")
    print(f"Raw packet: {raw!r}")
    print(f"Raw hex   : {_hex_dump(raw)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive ZeroMQ door state simulator")
    parser.add_argument("--endpoint", default="ipc:///run/atom/doors.sock")
    parser.add_argument("--heartbeat-sec", type=float, default=0.5)
    args = parser.parse_args()

    publisher = DoorPublisher(args.endpoint)
    store = DoorStateStore()
    store.update_from_doors({1: 0, 2: 0, 3: 0}, time.time())

    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(args.heartbeat_sec):
            _publish(store, publisher)

    hb_thread = threading.Thread(target=heartbeat_loop, name="door-sim-heartbeat", daemon=True)
    hb_thread.start()

    print(f"Door simulator started on {args.endpoint}")
    print("Commands: 1/2/3 toggle door, o=open all, c=close all, p=publish now, q=quit")
    _publish(store, publisher)

    try:
        while True:
            cmd = input("> ").strip().lower()
            if not cmd:
                continue
            if cmd == "q":
                break
            if cmd == "1":
                doors = dict(store.last_doors_state)
                doors[1] = 0 if doors[1] == 1 else 1
                store.update_from_doors(doors, time.time())
                _publish(store, publisher)
                continue
            if cmd == "2":
                doors = dict(store.last_doors_state)
                doors[2] = 0 if doors[2] == 1 else 1
                store.update_from_doors(doors, time.time())
                _publish(store, publisher)
                continue
            if cmd == "3":
                doors = dict(store.last_doors_state)
                doors[3] = 0 if doors[3] == 1 else 1
                store.update_from_doors(doors, time.time())
                _publish(store, publisher)
                continue
            if cmd == "o":
                store.update_from_doors({1: 1, 2: 1, 3: 1}, time.time())
                _publish(store, publisher)
                continue
            if cmd == "c":
                store.update_from_doors({1: 0, 2: 0, 3: 0}, time.time())
                _publish(store, publisher)
                continue
            if cmd == "p":
                _publish(store, publisher)
                continue
            print("Unknown command. Use: 1/2/3/o/c/p/q")
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        hb_thread.join(timeout=1.0)
        publisher.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
