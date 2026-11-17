"""Locate (and download on first use) the MediaPipe face landmarker model."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

from moodmusic.config import data_dir
from moodmusic.resources import resource_path

log = logging.getLogger(__name__)

FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
_FILENAME = "face_landmarker.task"


def _bundled_path() -> Path | None:
    """The face landmarker shipped in the package/bundle, if any."""
    return resource_path(_FILENAME)


def face_landmarker_path() -> Path:
    bundled = _bundled_path()
    if bundled is not None:
        return bundled
    dest_dir = data_dir() / "models"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _FILENAME
    if dest.exists():
        return dest
    tmp = dest.with_name(_FILENAME + ".part")
    log.info("Downloading face landmarker model")
    try:
        resp = requests.get(FACE_LANDMARKER_URL, stream=True, timeout=60)
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                f.write(chunk)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest
