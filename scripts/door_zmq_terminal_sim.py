from __future__ import annotations

import argparse
import os
import select
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from door_gateway.protocol import DoorTelemetry, build_packet, configured_door_ids
from door_gateway.publisher import DoorPublisher
from door_gateway.state import DoorStateStore

OPEN_VOLTAGE = 0xAF
CLOSED_VOLTAGE = 0


def _build_raw_packet(doors: dict[int, DoorTelemetry], *, door_count: int) -> bytes:
    return build_packet(doors, door_count=door_count)


def _hex_dump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _publish(store: DoorStateStore, publisher: DoorPublisher, *, door_count: int, verbose: bool = True) -> None:
    snap = store.snapshot(time.time())
    publisher.publish_snapshot(snap)
    if verbose:
        raw = _build_raw_packet(snap.doors, door_count=door_count)
        print(f"Published doors={snap.doors} seq={snap.seq} stale={snap.stale}")
        print(f"Raw packet: {raw!r}")
        print(f"Raw hex   : {_hex_dump(raw)}")


def _read_key_nonblocking(timeout_sec: float = 0.1) -> str | None:
    if not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    ready, _, _ = select.select([fd], [], [], timeout_sec)
    if not ready:
        return None
    ch = os.read(fd, 1)
    if not ch:
        return None
    return ch.decode("utf-8", errors="ignore").lower()


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive ZeroMQ door state simulator")
    parser.add_argument("--endpoint", default="ipc:///run/doors.sock")
    parser.add_argument("--door-count", type=int, default=3)
    parser.add_argument("--heartbeat-sec", type=float, default=0.5)
    args = parser.parse_args()
    if args.door_count not in (3, 4):
        parser.error("--door-count must be 3 or 4")

    door_ids = configured_door_ids(args.door_count)
    publisher = DoorPublisher(args.endpoint, door_ids=door_ids)
    store = DoorStateStore(args.door_count)
    store.update_from_doors(
        {door_id: DoorTelemetry(state=0, voltage=CLOSED_VOLTAGE) for door_id in door_ids},
        time.time(),
    )

    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(args.heartbeat_sec):
            _publish(store, publisher, door_count=args.door_count, verbose=False)

    hb_thread = threading.Thread(target=heartbeat_loop, name="door-sim-heartbeat", daemon=True)
    hb_thread.start()

    print(f"Door simulator started on {args.endpoint}")
    digits_help = "/".join(str(door_id) for door_id in door_ids)
    print(f"Commands: {digits_help} toggle door, o=open all, c=close all, p=publish now, q=quit")
    print("Single-key mode: just press the key (no Enter).")
    _publish(store, publisher, door_count=args.door_count)

    def _toggle(door_id: int) -> None:
        doors = dict(store.last_doors_state)
        current = doors[door_id]
        next_state = 0 if current.state == 1 else 1
        doors[door_id] = DoorTelemetry(
            state=next_state,
            voltage=OPEN_VOLTAGE if next_state == 1 else CLOSED_VOLTAGE,
        )
        store.update_from_doors(doors, time.time())
        _publish(store, publisher, door_count=args.door_count)

    def _set_all(state: int) -> None:
        store.update_from_doors(
            {
                door_id: DoorTelemetry(
                    state=state,
                    voltage=OPEN_VOLTAGE if state == 1 else CLOSED_VOLTAGE,
                )
                for door_id in door_ids
            },
            time.time(),
        )
        _publish(store, publisher, door_count=args.door_count)

    try:
        if sys.stdin.isatty():
            import termios
            import tty

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            try:
                while True:
                    cmd = _read_key_nonblocking(0.1)
                    if cmd is None:
                        continue
                    if cmd == "q":
                        break
                    if cmd.isdigit() and int(cmd) in door_ids:
                        _toggle(int(cmd))
                        continue
                    if cmd == "o":
                        _set_all(1)
                        continue
                    if cmd == "c":
                        _set_all(0)
                        continue
                    if cmd == "p":
                        _publish(store, publisher, door_count=args.door_count)
                        continue
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        else:
            while True:
                cmd = input("> ").strip().lower()
                if not cmd:
                    continue
                if cmd == "q":
                    break
                if cmd.isdigit() and int(cmd) in door_ids:
                    _toggle(int(cmd))
                    continue
                if cmd == "o":
                    _set_all(1)
                    continue
                if cmd == "c":
                    _set_all(0)
                    continue
                if cmd == "p":
                    _publish(store, publisher, door_count=args.door_count)
                    continue
                print(f"Unknown command. Use: {digits_help}/o/c/p/q")
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        hb_thread.join(timeout=1.0)
        publisher.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
