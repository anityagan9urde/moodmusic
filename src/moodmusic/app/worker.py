"""Vision worker thread: camera -> face -> emotion -> baseline -> smoother.

Camera, tracker and model are created inside run() so MediaPipe/ONNX objects live
on the worker thread. Frames stay in memory; nothing is written to disk.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from moodmusic.mood.calibration import Baseline, Calibrator, apply_baseline, save_baseline
from moodmusic.vision.face import crop_face
from moodmusic.vision.quality import assess_quality
from moodmusic.vision.types import EmotionReading, FaceObservation

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 20
ERROR_BACKOFF_S = 2.0
LANDMARK_STRIDE = 12


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def _annotated_qimage(frame_bgr: np.ndarray, obs: FaceObservation) -> QImage:
    img = frame_bgr.copy()
    h, w = img.shape[:2]
    if obs.bbox is not None:
        x, y, bw, bh = obs.bbox
        cv2.rectangle(img, (x, y), (x + bw, y + bh), (0, 200, 0), 2)
    if obs.landmarks is not None:
        for px, py in obs.landmarks[::LANDMARK_STRIDE, :2]:
            cv2.circle(img, (int(px * w), int(py * h)), 1, (0, 255, 255), -1)
    rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class VisionWorker(QThread):
    mood = Signal(object)
    quality = Signal(object)
    face_present = Signal(bool)
    reading = Signal(object)
    preview = Signal(object)
    camera_status = Signal(str)
    calibration_progress = Signal(float)
    calibration_done = Signal(object)

    def __init__(self, camera_factory, tracker_factory, model_factory,
                 baseline: Baseline | None, smoother, corrections, fps: float = 8,
                 calibration_seconds: float = 20.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 baseline_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self._camera_factory = camera_factory
        self._tracker_factory = tracker_factory
        self._model_factory = model_factory
        self.baseline = baseline
        self._smoother = smoother
        self._corrections = corrections
        self._fps = fps
        self._calibration_seconds = calibration_seconds
        self._clock = clock
        self._sleep = sleep
        self._baseline_path = baseline_path
        self._stop_flag = threading.Event()
        self._preview = False
        self._cmds: queue.Queue = queue.Queue()
        self._calibrator: Calibrator | None = None
        self._last_status: str | None = None
        self._last_face: bool | None = None
        self._last_quality = None

    # ---- thread-safe controls -------------------------------------------
    def start_calibration(self) -> None:
        self._cmds.put(("calibrate", None))

    def set_preview(self, enabled: bool) -> None:
        self._preview = bool(enabled)

    def force_mood(self, group) -> None:
        self._cmds.put(("force", group))

    def set_hold_seconds(self, seconds: float) -> None:
        self._cmds.put(("hold", seconds))

    def stop(self) -> None:
        self._stop_flag.set()
        if not self.wait(2000):
            log.warning("Vision worker did not stop within 2 s")

    # ---- thread body ----------------------------------------------------
    def run(self) -> None:
        camera = tracker = model = None
        try:
            try:
                camera = self._camera_factory()
                tracker = self._tracker_factory()
                model = self._model_factory()
            except Exception:
                log.exception("Vision setup failed")
                self.camera_status.emit("unavailable")
                return
            self._loop(camera, tracker, model)
        finally:
            for closer in (getattr(camera, "release", None), getattr(tracker, "close", None)):
                if closer is not None:
                    try:
                        closer()
                    except Exception:
                        log.exception("Cleanup failed")

    def _loop(self, camera, tracker, model) -> None:
        interval = 1.0 / self._fps
        errors = 0
        while not self._stop_flag.is_set():
            started = self._clock()
            try:
                self._step(camera, tracker, model)
                errors = 0
            except Exception:
                errors += 1
                log.exception("Vision iteration failed")
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    self.camera_status.emit("unavailable")
                    self._last_status = "unavailable"
                    self._backoff()
                    errors = 0
            remaining = interval - (self._clock() - started)
            if remaining > 0:
                self._sleep(remaining)

    def _backoff(self) -> None:
        waited = 0.0
        while waited < ERROR_BACKOFF_S and not self._stop_flag.is_set():
            self._sleep(0.1)
            waited += 0.1

    def _drain_commands(self, t: float) -> None:
        while True:
            try:
                kind, arg = self._cmds.get_nowait()
            except queue.Empty:
                return
            try:
                if kind == "calibrate":
                    self._calibrator = Calibrator(duration_s=self._calibration_seconds)
                    self.calibration_progress.emit(0.0)
                elif kind == "hold":
                    self._smoother.set_hold(arg)
                elif kind == "force":
                    self._apply_force(arg, t)
            except Exception:
                log.exception("Worker command %s failed", kind)

    def _apply_force(self, group, t: float) -> None:
        s = self._smoother.state
        try:
            self._corrections.record(predicted=s.group, actual=group,
                                     valence=s.valence, arousal=s.arousal)
        except Exception:
            log.exception("Recording correction failed")
        self.mood.emit(self._smoother.force(group, t))

    def _step(self, camera, tracker, model) -> None:
        t = self._clock()
        self._drain_commands(t)

        frame = camera.read()
        status = camera.status
        if status != self._last_status:
            self._last_status = status
            self.camera_status.emit(status)
        if frame is None:
            return

        obs = tracker.process(frame, int(t * 1000))
        present = obs.face_count > 0
        if present != self._last_face:
            self._last_face = present
            self.face_present.emit(present)

        if self._preview:
            self.preview.emit(_annotated_qimage(frame, obs))

        q = assess_quality(frame, obs)
        if q != self._last_quality:
            self._last_quality = q
            self.quality.emit(q)
        if not q.ok or obs.bbox is None:
            return

        raw = model.predict(crop_face(frame, obs.bbox))
        self.reading.emit(raw)

        if self._calibrator is not None:
            self._calibrate(raw, t)
            return

        r = apply_baseline(raw, self.baseline) if self.baseline else raw
        dv, da = self._corrections.bias()
        if dv or da:
            r = replace(r, valence=_clamp(r.valence + dv), arousal=_clamp(r.arousal + da))
        self.mood.emit(self._smoother.update(r, t))

    def _calibrate(self, raw: EmotionReading, t: float) -> None:
        cal = self._calibrator
        cal.add(raw, t)
        self.calibration_progress.emit(cal.progress)
        if not cal.done:
            return
        try:
            b = cal.result()
        except ValueError:
            log.warning("Calibration had too few samples; restarting")
            self._calibrator = Calibrator(duration_s=self._calibration_seconds)
            self.calibration_progress.emit(0.0)
            return
        self._calibrator = None
        try:
            save_baseline(b, self._baseline_path)
        except Exception:
            log.exception("Saving baseline failed")
        self.baseline = b
        self.calibration_done.emit(b)
