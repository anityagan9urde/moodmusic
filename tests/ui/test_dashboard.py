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
