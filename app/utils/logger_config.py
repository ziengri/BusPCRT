import logging
import sys
import threading


_exception_hooks_installed = False


def setup_logger(camId: str) -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format=f"%(asctime)s | %(levelname)s | [{camId}] | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f"app-{camId}.log", encoding="utf-8")
        ],
    )


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
