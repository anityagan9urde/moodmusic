from moodmusic.config import HOLD_SECONDS, Settings
from moodmusic.ui import settings_dialog as sd


class W:
    def __init__(self):
        self.calls = []

    def set_hold_seconds(self, s):
        self.calls.append(("hold", s))

    def start_calibration(self):
        self.calls.append("calibrate")


def test_save_applies_settings(qtbot, monkeypatch):
    saved = []
    monkeypatch.setattr(sd, "save_settings", lambda s: saved.append(1))
    monkeypatch.setattr(sd, "list_cameras", lambda: [0, 1])
    s, w = Settings(), W()
    d = sd.SettingsDialog(s, object(), w)
    qtbot.addWidget(d)
    d.sensitivity.setCurrentIndex(d.sensitivity.findData("responsive"))
    d.immediate.setChecked(True)
    d.away.setValue(0)
    d.start_login.setChecked(True)
    d.save()
    assert s.sensitivity == "responsive" and s.switch_mode == "immediate"
    assert s.away_pause_minutes == 0 and s.start_at_login
    assert ("hold", HOLD_SECONDS["responsive"]) in w.calls and saved


def test_recalibrate_and_logout(qtbot, monkeypatch):
    monkeypatch.setattr(sd, "list_cameras", lambda: [0])
    cleared = []
    monkeypatch.setattr(sd, "logout_spotify", lambda: cleared.append(1))
    w = W()
    d = sd.SettingsDialog(Settings(), object(), w)
    qtbot.addWidget(d)
    d.recalibrate_button.click()
    d.logout_button.click()
    assert "calibrate" in w.calls and cleared
