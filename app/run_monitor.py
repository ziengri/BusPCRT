from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.monitor import MonitorService, parse_monitor_args
from app.utils import install_exception_logging, setup_logger


def main() -> int:
    config = parse_monitor_args()
    setup_logger("monitor")
    install_exception_logging()

    service = MonitorService(config)
    service.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
