from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import zmq


def main() -> int:
    env_file = "door_gateway.env"
    if len(sys.argv) > 1:
        env_file = sys.argv[1]

    cmd = [sys.executable, "-m", "door_gateway.main", "--env-file", env_file, "--log-level", "DEBUG"]
    proc = subprocess.Popen(cmd)

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVHWM, 1)

    endpoint = "ipc:///run/atom/doors.sock"
    env_path = Path(env_file)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "ZMQ_IPC_ENDPOINT":
                endpoint = v.strip()
                break

    sock.connect(endpoint)
    sock.setsockopt_string(zmq.SUBSCRIBE, "doors.state")
    print(f"Listening on {endpoint}, topic doors.state")
    print("Press Ctrl+C to stop")

    try:
        while True:
            msg = sock.recv_string()
            topic, payload = msg.split(" ", 1)
            data = json.loads(payload)
            print(f"{topic}: {data}")
    except KeyboardInterrupt:
        return 0
    finally:
        sock.close(0)
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
