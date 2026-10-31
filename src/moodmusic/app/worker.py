"""Vision worker thread: camera -> face -> signals -> rolling features -> face state.

Camera, tracker and model are created inside run() so MediaPipe/ONNX objects live
on the worker thread. Frames stay in memory; nothing is written to disk.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from moodmusic.mood.baselines import PersonalBaselines, save_baselines
from moodmusic.mood.calibration import Baseline, Calibrator, apply_baseline, save_baseline
from moodmusic.mood.features import FeatureTracker
from moodmusic.mood.rules import decide, score_states
from moodmusic.vision.face import crop_face
from moodmusic.vision.signals import extract_signals
from moodmusic.vision.quality import assess_quality
from moodmusic.vision.types import EmotionReading, FaceObservation

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 20
ERROR_BACKOFF_S = 2.0
SETUP_RETRY_S = 10.0  # retry camera/model setup this often after it failed
LANDMARK_STRIDE = 12
STATE_EVERY_S = 0.5  # decide the face state twice a second, not every frame
BASELINE_SAVE_EVERY_S = 300.0


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
    features_ready = Signal(object)  # Features, for the dashboard's signals panel

    def __init__(self, camera_factory, tracker_factory, model_factory,
                 baseline: Baseline | None, state_tracker, corrections,
                 baselines: PersonalBaselines, fps: float = 8,
                 calibration_seconds: float = 20.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 baseline_path: Path | None = None, baselines_path: Path | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._camera_factory = camera_factory
        self._tracker_factory = tracker_factory
        self._model_factory = model_factory
        self.baseline = baseline
        self._state_tracker = state_tracker
        self._corrections = corrections
        self._baselines = baselines
        self._baselines_path = baselines_path
        self._features = FeatureTracker()
        self._prev_sig = None
        self._next_state_t: float | None = None
        self._last_state_t: float | None = None
        self._next_save_t: float | None = None
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

    def force_mood(self, state) -> None:
        """Not how I feel: `state` is the FaceState the user picked."""
        self._cmds.put(("force", state))

    def set_hold_seconds(self, seconds: float) -> None:
        self._cmds.put(("hold", seconds))

    def stop(self) -> None:
        self._stop_flag.set()
        if not self.wait(2000):
            log.warning("Vision worker did not stop within 2 s")

    # ---- thread body ----------------------------------------------------
    def run(self) -> None:
        parts: list = [None, None, None]  # camera, tracker, model
        try:
            if self._setup(parts):
                self._loop(*parts)
        finally:
            self._save_baselines()
            camera, tracker = parts[0], parts[1]
            for closer in (getattr(camera, "release", None), getattr(tracker, "close", None)):
                if closer is not None:
                    try:
                        closer()
                    except Exception:
                        log.exception("Cleanup failed")

    def _setup(self, parts: list) -> bool:
        """Create camera, tracker and model, retrying failures every SETUP_RETRY_S.

        Status "unavailable" if the camera failed, "model_failed" if tracker/model failed.
        Returns False if stopped first.
        """
        factories = (self._camera_factory, self._tracker_factory, self._model_factory)
        while not self._stop_flag.is_set():
            try:
                for i, factory in enumerate(factories):
                    if parts[i] is None:
                        parts[i] = factory()
                return True
            except Exception:
                log.exception("Vision setup failed; retrying in %.0f s", SETUP_RETRY_S)
                status = "unavailable" if parts[0] is None else "model_failed"
                if status != self._last_status:
                    self._last_status = status
                    self.camera_status.emit(status)
                self._backoff(SETUP_RETRY_S)
        return False

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

    def _backoff(self, seconds: float = ERROR_BACKOFF_S) -> None:
        waited = 0.0
        while waited < seconds and not self._stop_flag.is_set():
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
                    self._state_tracker.set_hold(arg)
                elif kind == "force":
                    self._apply_force(arg, t)
            except Exception:
                log.exception("Worker command %s failed", kind)

    def _apply_force(self, state, t: float) -> None:
        try:
            self._corrections.record(predicted=self._state_tracker.state.state, actual=state)
        except Exception:
            log.exception("Recording correction failed")
        self.mood.emit(self._state_tracker.force(state, t))

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
        if not q.ok or obs.bbox is None:  # absence (or an unusable face) still feeds features
            self._feed(FaceObservation(0), None, t)
            return

        raw = model.predict(crop_face(frame, obs.bbox))
        self.reading.emit(raw)
        self._feed(obs, apply_baseline(raw, self.baseline) if self.baseline else raw, t)
        if self._calibrator is not None:
            self._calibrate(raw, t)

    def _feed(self, obs: FaceObservation, reading, t: float) -> None:
        sig = extract_signals(obs, reading, self._prev_sig)
        self._prev_sig = sig if sig.face else None
        self._features.add(sig, t)
        if self._next_state_t is None:
            self._next_state_t = t + STATE_EVERY_S
            self._next_save_t = t + BASELINE_SAVE_EVERY_S
            self._last_state_t = t
            return
        if t < self._next_state_t:
            return
        self._next_state_t = t + STATE_EVERY_S
        f = self._features.features(t)
        self._baselines.update(f, t - self._last_state_t)
        self._last_state_t = t
        if self._calibrator is None:
            scores = score_states(f, self._baselines, self._corrections.bias())
            decision = decide(scores, self._state_tracker.state.state)
            self.mood.emit(self._state_tracker.update(decision, f, t))
        self.features_ready.emit(f)
        if t >= self._next_save_t:
            self._next_save_t = t + BASELINE_SAVE_EVERY_S
            self._save_baselines()

    def _save_baselines(self) -> None:
        try:
            save_baselines(self._baselines, self._baselines_path)
        except Exception:
            log.exception("Saving signal baselines failed")

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
        self._baselines.calibrate_rest(self._features.features(t))
        self._save_baselines()
        self.baseline = b
        self.calibration_done.emit(b)
