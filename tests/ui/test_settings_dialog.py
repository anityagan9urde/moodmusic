from PySide6.QtCore import QObject, Signal

from moodmusic.config import HOLD_SECONDS, Settings
from moodmusic.ui import settings_dialog as sd


class W(QObject):
    calibration_done = Signal(object)

    def __init__(self):
        super().__init__()
        self.calls = []

    def set_hold_seconds(self, s):
        self.calls.append(("hold", s))

    def start_calibration(self):
        self.calls.append("calibrate")


class Scan:
    def __init__(self):
        self.rescans = 0

    def rescan(self):
        self.rescans += 1


PLAYLISTS = lambda: [("p1", "Mix", 3), ("p2", "Gym", 9)]  # noqa: E731


def make(qtbot, monkeypatch, settings=None, scan=None, playlists_fn=PLAYLISTS):
    monkeypatch.setattr(sd, "list_cameras", lambda: [0, 1])
    monkeypatch.setattr(sd, "save_settings", lambda s: None)
    monkeypatch.setattr(sd, "logout_spotify", lambda: None)
    w = W()
    d = sd.SettingsDialog(settings or Settings(), object(), w, scan, playlists_fn=playlists_fn)
    qtbot.addWidget(d)
    qtbot.waitUntil(lambda: "Loading" not in d.playlist_status.text(), timeout=3000)
    return d, w


def test_save_applies_settings(qtbot, monkeypatch):
    s = Settings()
    d, w = make(qtbot, monkeypatch, s)
    d.sensitivity.setCurrentIndex(d.sensitivity.findData("responsive"))
    d.immediate.setChecked(True)
    d.away.setValue(0)
    d.start_login.setChecked(True)
    d.save()
    assert s.sensitivity == "responsive" and s.switch_mode == "immediate"
    assert s.away_pause_minutes == 0 and s.start_at_login
    assert ("hold", HOLD_SECONDS["responsive"]) in w.calls


def test_recalibrate_feedback_and_logout(qtbot, monkeypatch):
    cleared = []
    d, w = make(qtbot, monkeypatch)
    monkeypatch.setattr(sd, "logout_spotify", lambda: cleared.append(1))
    d.recalibrate_button.click()
    assert "calibrate" in w.calls and not d.recalibrate_button.isEnabled()
    assert "Calibrating" in d.note.text()
    w.calibration_done.emit(object())
    assert d.recalibrate_button.isEnabled() and "done" in d.note.text()
    d.logout_button.click()
    assert cleared


def test_playlist_combo_change_triggers_rescan(qtbot, monkeypatch):
    s, scan = Settings(), Scan()
    d, _ = make(qtbot, monkeypatch, s, scan)
    d.playlist.setCurrentIndex(d.playlist.findData("p2"))
    d.save()
    assert s.source_playlist_id == "p2" and scan.rescans == 1
    d.save()
    assert scan.rescans == 1  # unchanged source: no rescan


def test_saved_playlist_preserved_when_load_fails(qtbot, monkeypatch):
    def boom():
        raise RuntimeError("x")
    s, scan = Settings(source_playlist_id="p9"), Scan()
    d, _ = make(qtbot, monkeypatch, s, scan, playlists_fn=boom)
    assert not d.retry_button.isHidden()
    d.save()
    assert s.source_playlist_id == "p9" and scan.rescans == 0
