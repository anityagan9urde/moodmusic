import threading
import time

import numpy as np
import pytest
from PySide6.QtGui import QImage

from moodmusic.app.worker import VisionWorker
from moodmusic.mood.baselines import PersonalBaselines, load_baselines
from moodmusic.mood.calibration import Baseline
from moodmusic.mood.states import FaceState
from moodmusic.mood.tracker import FaceMood, StateTracker
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
    def __init__(self, bias=None):
        self.records = []
        self._bias = bias or {}

    def bias(self):
        return dict(self._bias)

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


class SpyStateTracker:
    def __init__(self):
        self.state = FaceMood(FaceState.HAPPY, 0.0, "smiling", 0.25, -0.3, {}, None)
        self.updates = []  # (decision, features, t)
        self.holds = []

    def update(self, decision, f, t):
        self.updates.append((decision, f, t))
        return self.state

    def set_hold(self, seconds):
        self.holds.append(seconds)

    def force(self, state, t):
        return FaceMood(state, t, "you said so")


class NoFaceTracker(FakeTracker):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def process(self, frame, ts):
        self.calls += 1
        return FaceObservation(0)


def make(tmp_path, model=None, camera=None, tracker=None, state_tracker=None,
         corrections=None, sleep=None, baselines=None, clock=None, **kw):
    camera = camera or FakeCamera()
    tracker = tracker or FakeTracker()
    model = model or FakeModel()
    w = VisionWorker(
        lambda: camera, lambda: tracker, lambda: model,
        kw.pop("baseline", None), state_tracker or StateTracker(hold_seconds=0.0),
        corrections or FakeCorrections(), baselines or PersonalBaselines(),
        fps=kw.pop("fps", 20), clock=clock or Clock(),
        sleep=sleep or (lambda s: time.sleep(0.001)),
        baseline_path=tmp_path / "b.json", baselines_path=tmp_path / "sb.json", **kw)
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
    moods = []
    w.mood.connect(moods.append)
    try:
        w.start()
        qtbot.waitUntil(lambda: len(moods) >= 2, timeout=3000)
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


def test_force_mood_records_state_correction(qtbot, tmp_path):
    spy = SpyStateTracker()
    w, *_ = make(tmp_path, state_tracker=spy)
    try:
        with qtbot.waitSignal(w.mood, timeout=3000):
            w.start()
        with qtbot.waitSignal(w.mood, timeout=3000,
                              check_params_cb=lambda s: s.state == FaceState.DEEP_THOUGHT):
            w.force_mood(FaceState.DEEP_THOUGHT)
    finally:
        w.stop()
    assert w._corrections.records[0] == {"predicted": FaceState.HAPPY,
                                         "actual": FaceState.DEEP_THOUGHT}


def test_no_face_frames_feed_absence(qtbot, tmp_path):
    spy, trk = SpyStateTracker(), NoFaceTracker()
    w, _, _, model = make(tmp_path, tracker=trk, state_tracker=spy)
    try:
        w.start()
        qtbot.waitUntil(lambda: len(spy.updates) >= 2, timeout=3000)
    finally:
        w.stop()
    assert model.calls == 0
    f = spy.updates[-1][1]
    assert f.face_ratio_10s == 0.0 and f.observed_s == 0.0


class SeqCamera(FakeCamera):
    def __init__(self, none_reads):
        super().__init__()
        self.none_reads = none_reads
        self.log = []
        self.reads = 0
        self.status = "reconnecting"

    def read(self):
        self.reads += 1
        self.log.append("read")
        if self.reads <= self.none_reads:
            return None
        self.status = "ok"
        return _frame()


def test_camera_none_skips_tracker_and_status_on_change(qtbot, tmp_path):
    cam = SeqCamera(none_reads=6)
    trk = NoFaceTracker()
    seen_reads = []
    orig = trk.process
    trk.process = lambda f, ts: (seen_reads.append(cam.reads), orig(f, ts))[1]
    w, *_ = make(tmp_path, camera=cam, tracker=trk)
    statuses = []
    w.camera_status.connect(statuses.append)
    try:
        w.start()
        qtbot.waitUntil(lambda: trk.calls >= 1, timeout=3000)
        qtbot.waitUntil(lambda: len(statuses) >= 2, timeout=3000)
    finally:
        w.stop()
    assert statuses == ["reconnecting", "ok"]
    assert min(seen_reads) > cam.none_reads  # tracker never ran on a None read


class AlwaysFailCamera(FakeCamera):
    def __init__(self):
        super().__init__()
        self.reads = 0

    def read(self):
        self.reads += 1
        raise RuntimeError("camera exploded")


def test_twenty_errors_emit_unavailable_back_off_and_reset(qtbot, tmp_path):
    cam = AlwaysFailCamera()
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        time.sleep(0.0005)

    w, *_ = make(tmp_path, camera=cam, sleep=sleep)
    statuses = []
    w.camera_status.connect(statuses.append)
    try:
        w.start()
        qtbot.waitUntil(lambda: len(statuses) >= 2, timeout=5000)
    finally:
        w.stop()
    assert statuses[:2] == ["unavailable", "unavailable"]
    assert cam.reads >= 40  # counter reset: second emission needs 20 more errors
    assert sum(1 for x in sleeps if x == 0.1) >= 19  # ~2 s backoff via injected sleep


def test_set_hold_seconds_reaches_state_tracker(qtbot, tmp_path):
    spy = SpyStateTracker()
    w, *_ = make(tmp_path, state_tracker=spy)
    try:
        w.start()
        w.set_hold_seconds(7.0)
        qtbot.waitUntil(lambda: spy.holds == [7.0], timeout=3000)
    finally:
        w.stop()


def test_emotion_baseline_applied_before_features(qtbot, tmp_path):
    spy = SpyStateTracker()
    w, *_ = make(tmp_path, state_tracker=spy, baseline=Baseline(0.1, 0.05, 1.0))
    try:
        w.start()
        qtbot.waitUntil(lambda: len(spy.updates) >= 1, timeout=3000)
    finally:
        w.stop()
    f = spy.updates[0][1]
    # raw valence 0.4, arousal 0.2 minus the calibrated baseline
    assert f.valence_30s == pytest.approx(0.3) and f.arousal_30s == pytest.approx(0.15)


def test_state_bias_reaches_rules(qtbot, tmp_path, monkeypatch):
    from moodmusic.app import worker as wmod
    seen = []
    real = wmod.score_states

    def spy_scores(f, b, bias=None):
        seen.append(bias)
        return real(f, b, bias)
    monkeypatch.setattr(wmod, "score_states", spy_scores)
    w, *_ = make(tmp_path, corrections=FakeCorrections({FaceState.LOVE: 0.1}))
    try:
        w.start()
        qtbot.waitUntil(lambda: len(seen) >= 1, timeout=3000)
    finally:
        w.stop()
    assert seen[0] == {FaceState.LOVE: 0.1}


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TickingCamera(FakeCamera):
    """Advances a shared clock by one frame (1/8 s) per read, so time is deterministic."""
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.reads = 0

    def read(self):
        self.reads += 1
        self.clock.t += 0.125
        return _frame()


def test_emits_state_every_half_second_not_every_frame(qtbot, tmp_path):
    clock = ManualClock()
    cam = TickingCamera(clock)
    w, *_ = make(tmp_path, camera=cam, clock=clock)
    moods = []
    w.mood.connect(moods.append)
    try:
        w.start()
        qtbot.waitUntil(lambda: cam.reads >= 40, timeout=3000)  # 5 s of frames
    finally:
        w.stop()
    qtbot.wait(50)
    frames = cam.reads
    assert frames / 4 - 2 <= len(moods) <= frames / 4 + 2  # ~2 per second at 8 fps


def test_baselines_saved_on_stop(qtbot, tmp_path):
    w, *_ = make(tmp_path)
    with qtbot.waitSignal(w.mood, timeout=3000):
        w.start()
    w.stop()
    assert load_baselines(tmp_path / "sb.json").observed_s > 0


def test_calibration_sets_rest_baselines_and_saves(qtbot, tmp_path):
    b = PersonalBaselines()
    w, *_ = make(tmp_path, calibration_seconds=0.5, baselines=b)
    try:
        w.start_calibration()
        with qtbot.waitSignal(w.calibration_done, timeout=5000):
            w.start()
    finally:
        w.stop()
    assert "gaze_on_ratio_30s" in b.to_dict()["rest"]
    assert (tmp_path / "sb.json").exists()


def test_calibration_restarts_on_too_few_samples(qtbot, tmp_path):
    # tiny duration: calibrator is "done" after 2 samples (< 20) -> ValueError path
    w, *_ = make(tmp_path, calibration_seconds=0.01)
    progress, done = [], []
    w.calibration_progress.connect(progress.append)
    w.calibration_done.connect(done.append)
    try:
        w.start_calibration()
        w.start()
        qtbot.waitUntil(lambda: progress.count(0.0) >= 3, timeout=3000)
    finally:
        w.stop()
    assert done == [] and w.baseline is None
    assert not (tmp_path / "b.json").exists()


def test_stop_joins_within_2s(qtbot, tmp_path):
    w, *_ = make(tmp_path, fps=8)
    with qtbot.waitSignal(w.mood, timeout=3000):
        w.start()
    t0 = time.monotonic()
    w.stop()
    assert time.monotonic() - t0 < 2.0
    assert not w.isRunning()


def test_model_setup_failure_reports_and_retries(qtbot, tmp_path, monkeypatch):
    from moodmusic.app import worker as wmod
    monkeypatch.setattr(wmod, "SETUP_RETRY_S", 0.3)
    attempts = []
    model = FakeModel()

    def model_factory():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("onnx missing")
        return model
    camera, tracker = FakeCamera(), FakeTracker()
    w = VisionWorker(lambda: camera, lambda: tracker, model_factory, None,
                     StateTracker(hold_seconds=0.0), FakeCorrections(), PersonalBaselines(),
                     fps=20, clock=Clock(step=0.05), sleep=lambda s: time.sleep(0.001),
                     baseline_path=tmp_path / "b.json", baselines_path=tmp_path / "sb.json")
    statuses = []
    w.camera_status.connect(statuses.append)
    try:
        with qtbot.waitSignal(w.mood, timeout=5000):
            w.start()
    finally:
        w.stop()
    assert len(attempts) == 3 and statuses[0] == "model_failed"
    assert statuses.count("model_failed") == 1 and "ok" in statuses
    assert camera.released and tracker.closed


def test_setup_retry_stops_promptly(qtbot, tmp_path):
    def bad():
        raise RuntimeError("no model")
    w = VisionWorker(FakeCamera, FakeTracker, bad, None, StateTracker(hold_seconds=0.0),
                     FakeCorrections(), PersonalBaselines(), fps=20, clock=Clock(step=0.05),
                     sleep=lambda s: time.sleep(0.001), baseline_path=tmp_path / "b.json",
                     baselines_path=tmp_path / "sb.json")
    with qtbot.waitSignal(w.camera_status, timeout=3000) as sig:
        w.start()
    assert sig.args == ["model_failed"]
    t0 = time.monotonic()
    w.stop()
    assert time.monotonic() - t0 < 2.0 and not w.isRunning()
