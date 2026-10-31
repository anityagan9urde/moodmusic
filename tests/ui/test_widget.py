from PySide6.QtGui import QColor

from moodmusic.app.engine import EngineStatus
from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.intent import Mode
from moodmusic.mood.smoother import MoodState
from moodmusic.spotify.client import Device
from moodmusic.ui import mood_picker
from moodmusic.ui.common import DeviceButton
from moodmusic.ui.mood_picker import MoodPicker
from moodmusic.ui.widget import MoodWidget
from moodmusic.vision.types import QualityReport


def make(qtbot, engine, worker, now=1000.0):
    saved = []
    w = MoodWidget(engine, worker, clock=lambda: now, save=lambda s: saved.append(s.mode))
    qtbot.addWidget(w)
    w.saved = saved
    return w


def test_widget_shows_mood_and_song(qtbot, engine, worker, pick):
    w = make(qtbot, engine, worker, now=1000.0 + 6 * 60)
    worker.mood.emit(MoodState(MoodGroup.UPBEAT, since=1000.0))
    assert MoodGroup.UPBEAT.emoji in w.mood_label.text()
    assert "Upbeat" in w.mood_label.text()
    assert w.steady_label.text() == "steady for 6 min"
    engine.current_pick = pick
    engine.notify()
    assert w.title_label.text() == "Holocene"
    assert w.artist_label.text() == "Bon Iver"
    assert w.wrong_btn.isEnabled()


def test_widget_just_now_and_quality_issue(qtbot, engine, worker):
    w = make(qtbot, engine, worker, now=1010.0)
    worker.mood.emit(MoodState(MoodGroup.CHILL, since=1000.0))
    assert w.steady_label.text() == "just now"
    worker.quality.emit(QualityReport(False, "Too dark"))
    assert w.mood_label.text() == "Too dark"
    assert w.steady_label.text() == ""
    assert w.dot.color == QColor("#f5a623")
    worker.quality.emit(QualityReport(True))
    assert "Chill" in w.mood_label.text()


def test_wrong_vibe_disabled_without_pick(qtbot, engine, worker):
    w = make(qtbot, engine, worker)
    assert not w.wrong_btn.isEnabled()


def test_widget_status_dot_colors(qtbot, engine, worker):
    w = make(qtbot, engine, worker)
    assert w.dot.color == QColor("#3ddc84")
    assert w.dot.toolTip() == "All good"
    engine.status = EngineStatus("warning", "Can't reach Spotify. Retrying")
    engine.notify()
    assert w.dot.color == QColor("#f5a623")
    assert w.dot.toolTip() == "Can't reach Spotify. Retrying"
    engine.status = EngineStatus("error", "Open Spotify on any device")
    engine.notify()
    assert w.dot.color == QColor("#e5484d")


def test_mode_toggle_calls_engine(qtbot, engine, worker):
    w = make(qtbot, engine, worker)
    w.mode_toggle.lift_btn.click()
    assert ("set_mode", Mode.LIFT) in engine.calls
    assert engine.settings.mode == "lift"
    assert w.saved == ["lift"]
    w.mode_toggle.match_btn.click()
    assert engine.calls[-1] == ("set_mode", Mode.MATCH)
    assert engine.settings.mode == "match"


def test_wrong_vibe_opens_picker_and_calls_engine(qtbot, engine, worker, pick, monkeypatch):
    w = make(qtbot, engine, worker)
    engine.current_pick = pick
    engine.notify()
    monkeypatch.setattr(MoodPicker, "ask", staticmethod(lambda parent, title: MoodGroup.INTENSE))
    w.wrong_btn.click()
    assert ("wrong_vibe", MoodGroup.INTENSE) in engine.calls


def test_wrong_vibe_cancel_does_nothing(qtbot, engine, worker, pick, monkeypatch):
    w = make(qtbot, engine, worker)
    engine.current_pick = pick
    engine.notify()
    monkeypatch.setattr(MoodPicker, "ask", staticmethod(lambda parent, title: None))
    w.wrong_btn.click()
    assert not [c for c in engine.calls if c[0] == "wrong_vibe"]


def test_not_how_i_feel_forces_mood_on_worker(qtbot, engine, worker, monkeypatch):
    w = make(qtbot, engine, worker)
    monkeypatch.setattr(MoodPicker, "ask", staticmethod(lambda parent, title: MoodGroup.FOCUS))
    w.feel_btn.click()
    assert ("force_mood", MoodGroup.FOCUS) in worker.calls


def test_transport_buttons(qtbot, engine, worker):
    w = make(qtbot, engine, worker)
    w.prev_btn.click()
    w.pause_btn.click()
    w.next_btn.click()
    assert [c[0] for c in engine.calls] == ["previous", "toggle_pause", "skip"]


def test_choose_device_button_and_menu(qtbot, engine, worker, monkeypatch):
    w = make(qtbot, engine, worker)
    w.show()
    assert w.device_btn.isHidden()
    engine.status = EngineStatus("error", "Choose a Spotify device")
    engine.devices = [Device("d1", "Laptop", "Computer", False)]
    engine.notify()
    assert not w.device_btn.isHidden()
    monkeypatch.setattr(DeviceButton, "_popup", staticmethod(lambda menu: menu.actions()[0]))
    w.device_btn.click()
    assert ("set_device", "d1") in engine.calls


def test_advanced_button_emits(qtbot, engine, worker):
    w = make(qtbot, engine, worker)
    with qtbot.waitSignal(w.switch_view) as sig:
        w.advanced_btn.click()
    assert sig.args == ["advanced"]


def test_mood_picker_has_five_options():
    assert list(mood_picker.CHOICES) == [
        MoodGroup.UPBEAT, MoodGroup.CHILL, MoodGroup.MELANCHOLY, MoodGroup.INTENSE, MoodGroup.FOCUS]


def test_status_dot_shows_camera_problems(qtbot, engine, worker):
    from moodmusic.ui.common import ERR, OK, WARN
    from moodmusic.ui.widget import MoodWidget
    w = MoodWidget(engine, worker)
    qtbot.addWidget(w)
    worker.camera_status.emit("unavailable")
    assert w.dot.color == ERR
    assert w.dot.toolTip() == ("Camera unavailable. Check it's connected and not used by "
                               "another app")
    engine.notify()  # engine refreshes must not hide the camera problem
    assert w.dot.color == ERR
    worker.camera_status.emit("reconnecting")
    assert w.dot.color == WARN and w.dot.toolTip() == "Reconnecting to camera…"
    worker.camera_status.emit("model_failed")
    assert w.dot.color == ERR and w.dot.toolTip() == "Mood model failed to load. See the log."
    worker.camera_status.emit("ok")
    assert w.dot.color == OK and w.dot.toolTip() == "All good"
