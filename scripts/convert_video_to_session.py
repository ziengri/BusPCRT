from __future__ import annotations

import argparse
from pathlib import Path

import cv2


from video_session import SessionWriter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert regular video to MKV(FFV1)+meta session files."
    )
    parser.add_argument("--input", required=True, help="Path to input video file")
    parser.add_argument("--output-dir", required=True, help="Output directory for session files")
    parser.add_argument("--camera-id", required=True, help="Camera id for target session")
    parser.add_argument("--width", type=int, required=True, help="Target frame width")
    parser.add_argument("--height", type=int, required=True, help="Target frame height")
    parser.add_argument("--fps", type=int, default=25, help="Target nominal FPS")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open input video: {input_path}")

    writer = SessionWriter(
        output_dir=args.output_dir,
        camera_id=args.camera_id,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[1] != args.width or frame.shape[0] != args.height:
                frame = cv2.resize(frame, (args.width, args.height), interpolation=cv2.INTER_LINEAR)
            writer.write_frame(frame)
    finally:
        cap.release()

    meta_path = writer.close()
    print(f"Video: {writer.video_path}")
    print(f"Meta: {meta_path}")
    print(f"Frames written: {writer.frame_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
