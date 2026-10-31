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
    return log_path
