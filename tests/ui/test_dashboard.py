from PySide6.QtGui import QImage

from moodmusic.app.engine import EngineStatus
from moodmusic.config import Settings
from moodmusic.mood.calibration import Baseline
from moodmusic.mood.states import FaceState
from moodmusic.mood.tracker import FaceMood
from moodmusic.ui.dashboard import EMOTIONS, Dashboard
from moodmusic.vision.types import EmotionReading


def make(qtbot, engine, worker, **kw):
    d = Dashboard(engine, worker, save=lambda s: None, **kw)
    qtbot.addWidget(d)
    return d


def test_dashboard_enables_preview_on_show_and_disables_on_hide(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    d.show()
    assert ("set_preview", True) in worker.calls
    d.hide()
    assert worker.calls[-1] == ("set_preview", False)


def test_state_card_shows_state_duration_and_reason(qtbot, engine, worker):
    clock = [400.0]
    d = make(qtbot, engine, worker, clock=lambda: clock[0])
    worker.mood.emit(FaceMood(FaceState.LOVE, 40.0, "soft smile, shy glances away"))
    assert d.state_label.text() == "🥰 Love / shy"
    assert "6 min" in d.state_detail.text() and "soft smile" in d.state_detail.text()


def test_state_bars_follow_scores_and_mark_current(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    worker.mood.emit(FaceMood(FaceState.FOCUSED, 0.0))
    worker.scores_ready.emit({s: 0.0 for s in FaceState} | {FaceState.FOCUSED: 0.82,
                                                            FaceState.TIRED: 0.15})
    assert d.state_bars.values[FaceState.FOCUSED] == 82
    assert d.state_bars.values[FaceState.TIRED] == 15
    assert d.state_bars.current == FaceState.FOCUSED
    assert len(d.state_bars.values) == len(FaceState)
    d.state_bars.resize(300, 200)
    assert not d.state_bars.grab().isNull()


def test_emotions_are_shown_relative_to_resting_face(qtbot, engine, worker):
    rest = {e: 0.0 for e in EMOTIONS} | {"anger": 0.25, "sadness": 0.6, "neutral": 0.15}
    worker.baseline = Baseline(-0.5, -0.1, 1.0, rest)
    d = make(qtbot, engine, worker)
    now = dict(rest) | {"anger": 0.27, "happiness": 0.2, "sadness": 0.4}
    worker.reading.emit(EmotionReading(now, 0.0, 0.0))
    deltas = d.emotions.deltas
    assert deltas["anger"] == 2  # resting anger reads as ~0, not 27%
    assert deltas["happiness"] == 20 and deltas["sadness"] == -20
    assert d.emotions.text_for("anger") == "≈ rest"
    assert d.emotions.text_for("sadness") == "−20"


def test_emotions_raw_until_calibrated_then_relative(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    probs = {e: 0.0 for e in EMOTIONS} | {"anger": 0.3}
    worker.reading.emit(EmotionReading(probs, 0.0, 0.0))
    assert d.emotions.deltas["anger"] == 30
    worker.calibration_done.emit(Baseline(0, 0, 1.0, probs))
    worker.reading.emit(EmotionReading(probs, 0.0, 0.0))
    assert d.emotions.deltas["anger"] == 0


def test_now_playing_controls_and_reason(qtbot, engine, worker, pick):
    d = make(qtbot, engine, worker)
    engine.current_pick = pick
    engine.is_playing = True
    engine.notify()
    assert "Holocene" in d.song_label.text()
    assert "calm + positive" in d.reason_label.text()
    assert d.pause_btn.toolTip() == "Pause" and not d.pause_btn.icon().isNull()
    d.prev_btn.click(); d.pause_btn.click(); d.next_btn.click()
    assert engine.calls[-3:] == [("previous",), ("toggle_pause",), ("skip",)]
    engine.is_playing = False
    engine.notify()
    assert d.pause_btn.toolTip() == "Play"


def test_settings_chips_show_current_settings(qtbot, engine, worker):
    engine.settings = Settings(switch_mode="immediate", sensitivity="relaxed",
                               away_pause_minutes=10)
    d = make(qtbot, engine, worker)
    texts = [c.text() for c in d.chips.chips]
    assert "On mood change: switch now" in texts
    assert "Reacts after: 90 s" in texts
    assert "Away pause: 10 min" in texts
    assert "Plays from: Liked Songs" in texts


def test_switch_chip_toggles_and_saves(qtbot, engine, worker):
    saved = []
    d = Dashboard(engine, worker, save=saved.append)
    qtbot.addWidget(d)
    d.chips.switch_chip.click()
    assert engine.settings.switch_mode == "immediate" and saved
    assert d.chips.switch_chip.text() == "On mood change: switch now"
    d.chips.switch_chip.click()
    assert engine.settings.switch_mode == "wait"
    assert d.chips.switch_chip.text() == "On mood change: finish song"


def test_other_chips_open_settings(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    with qtbot.waitSignal(d.settings_requested, timeout=500):
        d.chips.react_chip.click()


def test_testing_section_folds(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    d.show()
    assert not d.testing.isVisible()
    d.testing_toggle.click()
    assert d.testing.isVisible()


def test_status_line_and_preview_frame(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    engine.status = EngineStatus("error", "Open Spotify on any device")
    engine.notify()
    assert d.status_label.text() == "Open Spotify on any device"
    img = QImage(32, 24, QImage.Format.Format_RGB888)
    img.fill(0)
    worker.preview.emit(img)
    assert not d.preview_label.pixmap().isNull()


def test_chart_uses_history(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    engine.history = [(10.0, 0.2, -0.1), (20.0, 0.4, 0.3)]
    engine.notify()
    assert d.chart.history == engine.history


def test_dashboard_signals_panel_updates_from_features(qtbot, engine, worker):
    from moodmusic.mood.features import Features
    d = make(qtbot, engine, worker)
    worker.features_ready.emit(Features(gaze_on_ratio_30s=0.8, blink_rate_per_min_60s=30,
                                        stillness_s=15, smile_10s=0.5, brow_down_30s=0.4,
                                        mouth_press_30s=0.2, perclos_60s=0.1))
    v = d.signals.values
    assert v["Eyes on screen"] == 80 and v["Blink rate"] == 50 and v["Eyes open"] == 90
    assert set(d.signals.markers) == set(v)


def test_dashboard_timeline_segments_on_state_change(qtbot, engine, worker):
    clock = [100.0]
    d = make(qtbot, engine, worker, clock=lambda: clock[0])
    worker.mood.emit(FaceMood(FaceState.FOCUSED, 100.0))
    clock[0] = 160.0
    worker.mood.emit(FaceMood(FaceState.FOCUSED, 100.0))
    clock[0] = 200.0
    worker.mood.emit(FaceMood(FaceState.DEEP_THOUGHT, 200.0))
    assert d.timeline.segments == [(100.0, FaceState.FOCUSED), (200.0, FaceState.DEEP_THOUGHT)]


def test_not_how_i_feel_forces_state(qtbot, engine, worker, monkeypatch):
    from moodmusic.ui import dashboard
    monkeypatch.setattr(dashboard.MoodPicker, "ask_state", staticmethod(lambda *a: FaceState.SAD))
    d = make(qtbot, engine, worker)
    d.feel_btn.click()
    assert ("force_mood", FaceState.SAD) in worker.calls


def test_no_repeat_chip(qtbot, engine, worker):
    engine.settings = Settings(no_repeat_hours=6)
    d = make(qtbot, engine, worker)
    assert "No repeats for: 6 h" in [c.text() for c in d.chips.chips]


def test_folding_testing_section_shrinks_window(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    d.show()
    qtbot.wait(20)
    closed = d.height()
    d.testing_toggle.click()
    qtbot.waitUntil(lambda: d.height() > closed, timeout=1000)
    d.testing_toggle.click()
    qtbot.waitUntil(lambda: d.height() <= closed, timeout=1000)


def test_closing_dashboard_quits_the_app(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    d.show()
    with qtbot.waitSignal(d.quit_requested, timeout=500):
        d.close()
