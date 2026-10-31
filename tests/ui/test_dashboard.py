from PySide6.QtGui import QImage

from moodmusic.app.engine import EngineStatus
from moodmusic.ui.dashboard import EMOTIONS, Dashboard
from moodmusic.vision.types import EmotionReading


def make(qtbot, engine, worker):
    d = Dashboard(engine, worker, save=lambda s: None)
    qtbot.addWidget(d)
    return d


def test_dashboard_enables_preview_on_show_and_disables_on_hide(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    d.show()
    assert ("set_preview", True) in worker.calls
    d.hide()
    assert worker.calls[-1] == ("set_preview", False)


def test_emotion_bars_follow_readings(qtbot, engine, worker):
    d = make(qtbot, engine, worker)
    assert len(d.bars) == len(EMOTIONS) == 8
    probs = {e: 0.0 for e in EMOTIONS}
    probs["happiness"] = 0.75
    worker.reading.emit(EmotionReading(probs, 0.5, 0.2))
    assert d.bars["happiness"].value() == 75
    assert d.bars["anger"].value() == 0


def test_now_playing_and_reason(qtbot, engine, worker, pick):
    d = make(qtbot, engine, worker)
    engine.current_pick = pick
    engine.notify()
    assert "Holocene" in d.song_label.text()
    assert "calm + positive" in d.reason_label.text()


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
    d.chart.resize(200, 100)
    assert not d.chart.grab().isNull()


def test_dashboard_shows_state_and_reason(qtbot, engine, worker):
    from moodmusic.mood.states import FaceState
    from moodmusic.mood.tracker import FaceMood
    d = make(qtbot, engine, worker)
    worker.mood.emit(FaceMood(FaceState.LOVE, 5.0, "soft smile, shy glances away"))
    assert d.mood_label.text() == "🥰 Love / shy"
    assert d.mood_label.toolTip() == "Love / shy: soft smile, shy glances away"


def test_dashboard_signals_panel_updates_from_features(qtbot, engine, worker):
    from moodmusic.mood.features import Features
    d = make(qtbot, engine, worker)
    worker.features_ready.emit(Features(gaze_on_ratio_30s=0.8, blink_rate_per_min_60s=30,
                                        stillness_s=15, smile_10s=0.5, brow_down_30s=0.4,
                                        mouth_press_30s=0.2, perclos_60s=0.1))
    v = d.signals.values
    assert v["Eyes on screen"] == 80
    assert v["Blink rate"] == 50  # 30/min on a 0-60 scale
    assert v["Stillness"] == 50  # 15 s on a 0-30 s scale
    assert v["Smile"] == 50 and v["Tension"] == 30 and v["Eyes open"] == 90
    assert set(d.signals.markers) == set(v)  # every signal shows the user's baseline


def test_dashboard_timeline_segments_on_state_change(qtbot, engine, worker):
    from moodmusic.mood.states import FaceState
    from moodmusic.mood.tracker import FaceMood
    clock = [100.0]
    d = Dashboard(engine, worker, clock=lambda: clock[0], save=lambda s: None)
    qtbot.addWidget(d)
    worker.mood.emit(FaceMood(FaceState.FOCUSED, 100.0))
    clock[0] = 160.0
    worker.mood.emit(FaceMood(FaceState.FOCUSED, 100.0))  # same state: no new segment
    clock[0] = 200.0
    worker.mood.emit(FaceMood(FaceState.DEEP_THOUGHT, 200.0))
    assert d.timeline.segments == [(100.0, FaceState.FOCUSED), (200.0, FaceState.DEEP_THOUGHT)]
    d.timeline.resize(300, 20)
    assert not d.timeline.grab().isNull()
