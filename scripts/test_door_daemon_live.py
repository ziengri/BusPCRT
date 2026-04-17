from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import zmq


def _load_endpoint(config_env: str, env_file: str) -> str:
    endpoint = "ipc:///run/atom/doors.sock"
    for file_path in (config_env, env_file):
        path = Path(file_path)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "ZMQ_IPC_ENDPOINT":
                endpoint = v.strip()
    return endpoint


def main() -> int:
    config_env = "config.env"
    env_file = "door_gateway.env"
    if len(sys.argv) > 1:
        env_file = sys.argv[1]
    if len(sys.argv) > 2:
        config_env = sys.argv[2]

    cmd = [
        sys.executable,
        "-m",
        "door_gateway.main",
        "--config-env-file",
        config_env,
        "--env-file",
        env_file,
        "--log-level",
        "DEBUG",
    ]
    proc = subprocess.Popen(cmd)

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVHWM, 1)

    endpoint = _load_endpoint(config_env=config_env, env_file=env_file)

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
