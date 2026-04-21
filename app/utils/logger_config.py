import logging
import sys
import threading


_exception_hooks_installed = False


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int):
        super().__init__()
        self.max_level = int(max_level)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def setup_logger(cam_id: str, log_file: str | None = None) -> None:
    fmt = f"%(asctime)s | %(levelname)s | [{cam_id}] | %(name)s | %(message)s"

    stdout_handler = logging.StreamHandler(stream=sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    stdout_handler.setFormatter(logging.Formatter(fmt))

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(logging.Formatter(fmt))

    handlers: list[logging.Handler] = [stdout_handler, stderr_handler]
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(fmt))
        handlers.append(file_handler)

    logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)


def install_exception_logging(logger_name: str | None = None) -> None:
    """Log all uncaught exceptions via logging hooks."""
    global _exception_hooks_installed

    if _exception_hooks_installed:
        return

    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()

    def _sys_excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def _thread_excepthook(args: threading.ExceptHookArgs):
        if issubclass(args.exc_type, KeyboardInterrupt):
            return
        thread_name = args.thread.name if args.thread else "unknown"
        logger.critical(
            "Unhandled exception in thread %s",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _sys_excepthook
    threading.excepthook = _thread_excepthook
    _exception_hooks_installed = True
