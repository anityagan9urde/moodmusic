"""Webcam capture that survives disconnects. Frames stay in memory."""
from __future__ import annotations

import logging
import sys
import time
from typing import Callable

import cv2
import numpy as np

log = logging.getLogger(__name__)

MAX_FAILED_READS = 3
RETRY_INTERVAL_S = 2.0


def _backend() -> int:
    return cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def _open(factory: Callable, index: int):
    try:
        cap = factory(index, _backend())
    except Exception:
        log.exception("Camera open failed")
        return None
    try:
        if cap is not None and cap.isOpened():
            return cap
        if cap is not None:
            cap.release()
    except Exception:
        log.exception("Camera open check failed")
    return None


class CameraSource:
    def __init__(self, index: int, capture_factory: Callable = cv2.VideoCapture,
                 clock: Callable[[], float] = time.monotonic):
        self._index = index
        self._factory = capture_factory
        self._clock = clock
        self._failures = 0
        self._ever_opened = False
        self._next_retry = 0.0
        self._cap = _open(capture_factory, index)
        if self._cap is not None:
            self._ever_opened = True
        else:
            self._next_retry = clock() + RETRY_INTERVAL_S

    @property
    def status(self) -> str:
        if self._cap is not None:
            return "ok"
        return "reconnecting" if self._ever_opened else "unavailable"

    def _drop(self) -> None:
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                log.exception("Camera release failed")

    def read(self) -> np.ndarray | None:
        try:
            if self._cap is None:
                now = self._clock()
                if now < self._next_retry:
                    return None
                self._cap = _open(self._factory, self._index)
                if self._cap is None:
                    self._next_retry = now + RETRY_INTERVAL_S
                    return None
                self._ever_opened = True
                self._failures = 0
            ok, frame = self._cap.read()
            if ok and frame is not None:
                self._failures = 0
                return frame
        except Exception:
            log.exception("Camera read failed")
        self._failures += 1
        if self._cap is not None and self._failures >= MAX_FAILED_READS:
            self._drop()
            self._next_retry = self._clock() + RETRY_INTERVAL_S
        return None

    def release(self) -> None:
        self._drop()


def list_cameras(max_index: int = 5, capture_factory: Callable = cv2.VideoCapture) -> list[int]:
    found = []
    for i in range(max_index):
        try:
            cap = capture_factory(i, _backend())
        except Exception:
            continue
        try:
            if cap.isOpened():
                found.append(i)
        except Exception:
            pass
        try:
            cap.release()
        except Exception:
            pass
    return found
