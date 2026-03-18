from __future__ import annotations

import argparse

import cv2

from video_session import SessionReader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play recorded session using meta.json")
    parser.add_argument("--meta", required=True, help="Path to session meta.json")
    parser.add_argument("--delay", type=int, default=1, help="Delay for cv2.waitKey in ms")
    parser.add_argument("--loop", action="store_true", help="Loop playback")
    parser.add_argument("--window-name", default="Session Player", help="OpenCV window name")
    return parser.parse_args()


def play_once(meta_path: str, delay: int, window_name: str) -> tuple[bool, int]:
    shown = 0
    with SessionReader(meta_path) as reader:
        for frame in reader:
            shown += 1
            cv2.imshow(window_name, frame)
            key = cv2.waitKey(delay) & 0xFF
            if key in (27, ord("q")):
                return False, shown
    return True, shown


def main() -> int:
    args = parse_args()
    should_continue = True

    try:
        while should_continue:
            should_continue, shown = play_once(args.meta, args.delay, args.window_name)
            if shown == 0:
                break
            if not args.loop:
                break
    finally:
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
