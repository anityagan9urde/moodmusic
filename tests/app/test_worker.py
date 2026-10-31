import threading
import time

import numpy as np
import pytest
from PySide6.QtGui import QImage

from moodmusic.app.worker import VisionWorker
from moodmusic.mood.calibration import Baseline
from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.smoother import MoodSmoother
from moodmusic.vision.types import EmotionReading, FaceObservation


def _frame():
    rng = np.random.default_rng(0)
    return rng.integers(90, 170, (240, 320, 3), dtype=np.uint8)


class FakeCamera:
    status = "ok"

    def __init__(self):
        self.released = False
        self.reads_after_release = 0

    def read(self):
        if self.released:
            self.reads_after_release += 1
        return _frame()

    def release(self):
        self.released = True


class FakeTracker:
    def __init__(self):
        self.closed = False

    def process(self, frame, ts):
        lm = np.tile(np.array([0.5, 0.5, 0.0], dtype=np.float32), (478, 1))
        lm[33, 0], lm[263, 0] = 0.4, 0.6
        return FaceObservation(1, (80, 60, 160, 120), {}, lm)

    def close(self):
        self.closed = True


class FakeModel:
    def __init__(self, fail_first=0):
        self.calls = 0
        self.fail_first = fail_first

    def predict(self, face_rgb):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("boom")
        return EmotionReading({"neutral": 0.5, "happy": 0.5}, 0.4, 0.2)


class FakeCorrections:
    def __init__(self):
        self.records = []

    def bias(self):
        return (0.0, 0.0)

    def record(self, **kw):
        self.records.append(kw)


class Clock:
    def __init__(self, step=0.005):
        self.t = 0.0
        self.step = step
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            self.t += self.step
            return self.t


def make(tmp_path, model=None, camera=None, tracker=None, **kw):
    camera = camera or FakeCamera()
    tracker = tracker or FakeTracker()
    model = model or FakeModel()
    w = VisionWorker(
        lambda: camera, lambda: tracker, lambda: model,
        kw.pop("baseline", None), MoodSmoother(hold_seconds=0.0), FakeCorrections(),
        fps=kw.pop("fps", 1000), clock=Clock(), sleep=lambda s: time.sleep(0.001),
        baseline_path=tmp_path / "b.json", **kw)
    return w, camera, tracker, model


def test_emits_mood_and_quality(qtbot, tmp_path):
    w, cam, trk, _ = make(tmp_path)
    try:
        with qtbot.waitSignals([w.quality, w.mood, w.face_present], timeout=3000):
            w.start()
    finally:
        w.stop()
    assert not w.isRunning()
    assert cam.released and trk.closed
    assert cam.reads_after_release == 0


def test_calibration_emits_progress_and_baseline(qtbot, tmp_path):
    w, *_ = make(tmp_path, calibration_seconds=0.5)
    progress = []
    w.calibration_progress.connect(progress.append)
    try:
        w.start_calibration()
        with qtbot.waitSignal(w.calibration_done, timeout=5000) as blocker:
            w.start()
    finally:
        w.stop()
    b = blocker.args[0]
    assert isinstance(b, Baseline)
    assert b.valence == pytest.approx(0.4)
    assert progress and progress[-1] >= 1.0
    assert w.baseline == b
    assert (tmp_path / "b.json").exists()


def test_exception_in_model_does_not_kill_thread(qtbot, tmp_path):
    w, *_ = make(tmp_path, model=FakeModel(fail_first=3))
    try:
        with qtbot.waitSignal(w.mood, timeout=3000):
            w.start()
        assert w.isRunning()
    finally:
        w.stop()


def test_no_preview_when_disabled(qtbot, tmp_path):
    w, *_ = make(tmp_path)
    previews = []
    w.preview.connect(previews.append)
    try:
        with qtbot.waitSignals([w.mood, w.mood], timeout=3000):
            w.start()
    finally:
        w.stop()
    assert previews == []


def test_preview_emitted_when_enabled(qtbot, tmp_path):
    w, *_ = make(tmp_path)
    w.set_preview(True)
    try:
        with qtbot.waitSignal(w.preview, timeout=3000) as blocker:
            w.start()
    finally:
        w.stop()
    img = blocker.args[0]
    assert isinstance(img, QImage) and img.width() == 320 and img.height() == 240


def test_force_mood_records_correction_and_emits(qtbot, tmp_path):
    w, *_ = make(tmp_path)
    try:
        with qtbot.waitSignal(w.mood, timeout=3000):
            w.start()
        with qtbot.waitSignal(w.mood, timeout=3000,
                              check_params_cb=lambda s: s.group == MoodGroup.MELANCHOLY):
            w.force_mood(MoodGroup.MELANCHOLY)
    finally:
        w.stop()
    rec = w._corrections.records
    assert rec and rec[0]["actual"] == MoodGroup.MELANCHOLY


def test_stop_joins_within_2s(qtbot, tmp_path):
    w, *_ = make(tmp_path, fps=8)
    with qtbot.waitSignal(w.mood, timeout=3000):
        w.start()
    t0 = time.monotonic()
    w.stop()
    assert time.monotonic() - t0 < 2.0
    assert not w.isRunning()
