"""Rotating file logging."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from moodmusic.config import data_dir


def setup_logging() -> Path:
    log_path = data_dir() / "moodmusic.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(
        isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == log_path
        for h in root.handlers
    ):
        handler = RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    _enable_crash_dump()
    return log_path


_crash_file = None  # kept open for the life of the process (faulthandler needs the fd)


def _enable_crash_dump() -> None:
    """On a native crash (e.g. inside Qt), write every thread's Python stack to crash.log."""
    global _crash_file
    if _crash_file is not None:
        return
    import faulthandler
    try:
        _crash_file = open(data_dir() / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError:
        logging.getLogger(__name__).warning("Could not enable crash dumps", exc_info=True)
