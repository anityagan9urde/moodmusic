from PySide6.QtCore import QObject, Signal

from moodmusic.app.engine import EngineStatus
from moodmusic.config import HOLD_SECONDS, Settings
from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.intent import Mode
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


class Lib:
    def counts(self):
        return {MoodGroup.FOCUS: 10, MoodGroup.PARTY: 5, MoodGroup.UNSORTED: 2}


class Sel:
    library = Lib()


class E:
    def __init__(self, settings):
        self.settings = settings
        self.status = EngineStatus("ok", "")
        self.selector = Sel()
        self.modes = []

    def set_mode(self, mode):
        self.modes.append(mode)


class Scan:
    def __init__(self):
        self.rescans = 0

    def rescan(self):
        self.rescans += 1


PLAYLISTS = lambda: [("p1", "Mix", 3), ("p2", "Gym", 9)]  # noqa: E731


def make(qtbot, monkeypatch, settings=None, scan=None, playlists_fn=PLAYLISTS, autostart=None):
    saved = []
    monkeypatch.setattr(sd, "list_cameras", lambda: [0, 1])
    monkeypatch.setattr(sd, "save_settings", saved.append)
    monkeypatch.setattr(sd, "logout_spotify", lambda: None)
    s = settings or Settings()
    w = W()
    d = sd.SettingsDialog(s, E(s), w, scan, playlists_fn=playlists_fn,
                          autostart_fn=autostart or (lambda on: True))
    qtbot.addWidget(d)
    qtbot.waitUntil(lambda: "Loading" not in d.playlist_status.text(), timeout=3000)
    return d, w, saved


def test_changes_apply_immediately_without_save(qtbot, monkeypatch):
    s = Settings()
    d, w, saved = make(qtbot, monkeypatch, s)
    d.react.select("responsive")
    assert s.sensitivity == "responsive" and ("hold", HOLD_SECONDS["responsive"]) in w.calls
    d.switch.select("immediate")
    assert s.switch_mode == "immediate"
    d.away.setCurrentIndex(d.away.findData(0))
    assert s.away_pause_minutes == 0
    assert saved  # persisted on change


def test_plain_labels_with_seconds():
    labels = [label for label, _ in sd.REACT_CHOICES]
    assert labels == [f"Quick · {HOLD_SECONDS['responsive']} s",
                      f"Balanced · {HOLD_SECONDS['normal']} s",
                      f"Steady · {HOLD_SECONDS['relaxed']} s"]


def test_controls_show_current_settings(qtbot, monkeypatch):
    s = Settings(sensitivity="relaxed", switch_mode="immediate", mode="lift",
                 away_pause_minutes=10)
    d, _, _ = make(qtbot, monkeypatch, s)
    assert d.react.value() == "relaxed" and d.switch.value() == "immediate"
    assert d.music_style.value() == "lift" and d.away.currentData() == 10
    assert "17 songs" in d.source_hint.text() and "2 not sorted" in d.source_hint.text()


def test_music_style_sets_engine_mode(qtbot, monkeypatch):
    s = Settings()
    d, _, _ = make(qtbot, monkeypatch, s)
    d.music_style.select("lift")
    assert s.mode == "lift" and d.engine.modes == [Mode.LIFT]


def test_custom_away_value_is_kept(qtbot, monkeypatch):
    d, _, _ = make(qtbot, monkeypatch, Settings(away_pause_minutes=7))
    assert d.away.currentData() == 7


def test_start_at_login_calls_os_and_reverts_when_unsupported(qtbot, monkeypatch):
    calls = []
    s = Settings()
    d, _, _ = make(qtbot, monkeypatch, s, autostart=lambda on: calls.append(on) or True)
    d.start_login.setChecked(True)
    assert calls == [True] and s.start_at_login
    s2 = Settings()
    d2, _, _ = make(qtbot, monkeypatch, s2, autostart=lambda on: False)
    d2.start_login.setChecked(True)
    assert not d2.start_login.isChecked() and not s2.start_at_login
    assert "isn't available" in d2.login_hint.text()


def test_recalibrate_feedback_and_logout(qtbot, monkeypatch):
    cleared = []
    d, w, _ = make(qtbot, monkeypatch)
    monkeypatch.setattr(sd, "logout_spotify", lambda: cleared.append(1))
    d.recalibrate_button.click()
    assert "calibrate" in w.calls and not d.recalibrate_button.isEnabled()
    assert "Calibrating" in d.note.text()
    w.calibration_done.emit(object())
    assert d.recalibrate_button.isEnabled() and "done" in d.note.text()
    d.logout_button.click()
    assert cleared


def test_spotify_status_line(qtbot, monkeypatch):
    d, _, _ = make(qtbot, monkeypatch)
    assert "Connected" in d.spotify_status.text()
    d.engine.status = EngineStatus("error", "Spotify login expired. Please log in again")
    d.refresh_spotify()
    assert "log in again" in d.spotify_status.text()


def test_advanced_is_folded(qtbot, monkeypatch):
    d, _, _ = make(qtbot, monkeypatch)
    d.show()
    assert not d.client_id.isVisible()
    d.advanced_toggle.click()
    assert d.client_id.isVisible() and d.log_button.isVisible()


def test_client_id_applies_when_editing_finishes(qtbot, monkeypatch):
    s, scan = Settings(spotify_client_id="old"), Scan()
    d, _, _ = make(qtbot, monkeypatch, s, scan)
    d.client_id.setText("new")
    d.client_id.editingFinished.emit()
    assert s.spotify_client_id == "new" and scan.rescans == 1


def test_playlist_change_rescans_once(qtbot, monkeypatch):
    s, scan = Settings(), Scan()
    d, _, _ = make(qtbot, monkeypatch, s, scan)
    d.playlist.setCurrentIndex(d.playlist.findData("p2"))
    assert s.source_playlist_id == "p2" and scan.rescans == 1
    d.react.select("normal")
    assert scan.rescans == 1  # unrelated change: no rescan


def test_saved_playlist_preserved_when_load_fails(qtbot, monkeypatch):
    def boom():
        raise RuntimeError("x")
    s, scan = Settings(source_playlist_id="p9"), Scan()
    d, _, _ = make(qtbot, monkeypatch, s, scan, playlists_fn=boom)
    assert not d.retry_button.isHidden()
    assert s.source_playlist_id == "p9" and scan.rescans == 0


def test_done_closes(qtbot, monkeypatch):
    d, _, _ = make(qtbot, monkeypatch)
    d.show()
    d.done_button.click()
    assert not d.isVisible()
