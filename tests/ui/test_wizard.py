import threading

from PySide6.QtCore import QObject, Signal

from moodmusic.config import Settings
from moodmusic.music.lastfm import LastFmError
from moodmusic.spotify.client import NotPremium, SpotifyError
from moodmusic.ui import wizard as wiz
from moodmusic.vision.types import QualityReport


class WizWorker(QObject):
    quality = Signal(object)
    preview = Signal(object)
    camera_status = Signal(str)
    calibration_progress = Signal(float)
    calibration_done = Signal(object)

    def __init__(self, index=0):
        super().__init__()
        self.index, self.calls = index, []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def set_preview(self, on):
        self.calls.append(("preview", on))

    def start_calibration(self):
        self.calls.append("calibrate")


def make(qtbot, monkeypatch, bundled=None, login_fn=None, validate_fn=None):
    monkeypatch.setattr(wiz, "bundled_lastfm_key", lambda: bundled)
    saved = []
    monkeypatch.setattr(wiz, "save_settings", lambda s: saved.append(s.setup_complete))
    workers = []

    def factory(index):
        w = WizWorker(index)
        workers.append(w)
        return w

    s = Settings()
    w = wiz.SetupWizard(s, login_fn=login_fn or (lambda cid, cancel=None: None), worker_factory=factory,
                        cameras_fn=lambda: [0, 1], playlists_fn=lambda: [("p1", "Mix", 3)],
                        validate_fn=validate_fn or (lambda key: None))
    qtbot.addWidget(w)
    return w, s, saved, workers


def test_spotify_page_blocks_next_until_logged_in(qtbot, monkeypatch):
    w, s, _, _ = make(qtbot, monkeypatch)
    page = w.page(wiz.PAGE_SPOTIFY)
    assert not page.isComplete()
    page.client_edit.setText("abc123")
    page.start_login()
    qtbot.waitUntil(page.isComplete, timeout=3000)
    assert s.spotify_client_id == "abc123"


def test_not_premium_shows_message(qtbot, monkeypatch):
    def login(cid, cancel=None):
        raise NotPremium("x")
    w, s, _, _ = make(qtbot, monkeypatch, login_fn=login)
    page = w.page(wiz.PAGE_SPOTIFY)
    page.client_edit.setText("abc")
    page.start_login()
    qtbot.waitUntil(lambda: "Premium" in page.status.text(), timeout=3000)
    assert "Spotify Premium is needed to control playback" in page.status.text()
    assert not page.isComplete()


def test_spotify_error_allows_retry(qtbot, monkeypatch):
    calls = []

    def login(cid, cancel=None):
        calls.append(cid)
        if len(calls) == 1:
            raise SpotifyError("boom")
    w, *_ = make(qtbot, monkeypatch, login_fn=login)
    page = w.page(wiz.PAGE_SPOTIFY)
    page.client_edit.setText("abc")
    page.start_login()
    qtbot.waitUntil(lambda: "boom" in page.status.text(), timeout=3000)
    assert page.login_button.isEnabled() and not page.isComplete()
    page.start_login()
    qtbot.waitUntil(page.isComplete, timeout=3000)


def test_lastfm_page_skipped_when_bundled_key(qtbot, monkeypatch):
    w, s, _, _ = make(qtbot, monkeypatch, bundled="KEY123")
    assert s.lastfm_api_key == "KEY123"
    assert w.page(wiz.PAGE_SPOTIFY).nextId() == wiz.PAGE_CAMERA


def test_lastfm_page_validates(qtbot, monkeypatch):
    def bad(key):
        raise LastFmError("Last.fm error 10: Invalid API key")
    w, s, _, _ = make(qtbot, monkeypatch, validate_fn=bad)
    assert w.page(wiz.PAGE_SPOTIFY).nextId() == wiz.PAGE_LASTFM
    page = w.page(wiz.PAGE_LASTFM)
    page.key_edit.setText("k")
    page.start_validate()
    qtbot.waitUntil(lambda: "Invalid API key" in page.status.text(), timeout=3000)
    assert not page.isComplete()


def test_lastfm_page_accepts_valid_key(qtbot, monkeypatch):
    w, s, _, _ = make(qtbot, monkeypatch)
    page = w.page(wiz.PAGE_LASTFM)
    page.key_edit.setText("goodkey")
    page.start_validate()
    qtbot.waitUntil(page.isComplete, timeout=3000)
    assert s.lastfm_api_key == "goodkey"


def test_camera_next_needs_ok_quality_and_worker_lifecycle(qtbot, monkeypatch):
    w, s, _, workers = make(qtbot, monkeypatch)
    cam = w.page(wiz.PAGE_CAMERA)
    cam.initializePage()
    assert len(workers) == 1 and "start" in workers[0].calls
    assert not cam.isComplete()
    workers[0].quality.emit(QualityReport(False, "Too dark"))
    assert "Too dark" in cam.quality_label.text() and not cam.isComplete()
    workers[0].quality.emit(QualityReport(True, None))
    assert cam.isComplete()
    cam.camera_combo.setCurrentIndex(1)
    assert "stop" in workers[0].calls and len(workers) == 2 and s.camera_index == 1
    assert not cam.isComplete()


def test_calibration_page(qtbot, monkeypatch):
    w, s, _, workers = make(qtbot, monkeypatch)
    w.page(wiz.PAGE_CAMERA).initializePage()
    cal = w.page(wiz.PAGE_CALIBRATION)
    cal.initializePage()
    assert "calibrate" in workers[0].calls and not cal.isComplete()
    workers[0].calibration_progress.emit(0.5)
    assert cal.progress.value() == 50
    workers[0].calibration_done.emit(object())
    assert cal.isComplete()


def test_source_page_selection(qtbot, monkeypatch):
    w, s, _, _ = make(qtbot, monkeypatch)
    src = w.page(wiz.PAGE_SOURCE)
    src.initializePage()
    qtbot.waitUntil(lambda: src.list.count() == 2, timeout=3000)
    src.list.setCurrentRow(1)
    assert src.selected_id() == "p1"
    src.list.setCurrentRow(0)
    assert src.selected_id() is None


def test_finish_sets_setup_complete_and_saves(qtbot, monkeypatch):
    w, s, saved, workers = make(qtbot, monkeypatch)
    w.page(wiz.PAGE_CAMERA).initializePage()
    src = w.page(wiz.PAGE_SOURCE)
    src.initializePage()
    qtbot.waitUntil(lambda: src.list.count() == 2, timeout=3000)
    src.list.setCurrentRow(1)
    w.accept()
    assert s.setup_complete and saved == [True]
    assert s.source_playlist_id == "p1"
    assert "stop" in workers[0].calls


def test_reject_stops_worker_without_saving(qtbot, monkeypatch):
    w, s, saved, workers = make(qtbot, monkeypatch)
    w.page(wiz.PAGE_CAMERA).initializePage()
    w.reject()
    assert "stop" in workers[0].calls and not s.setup_complete and saved == []


def test_camera_status_messages(qtbot, monkeypatch):
    w, s, _, workers = make(qtbot, monkeypatch)
    cam = w.page(wiz.PAGE_CAMERA)
    cam.initializePage()
    workers[0].quality.emit(QualityReport(True, None))
    workers[0].camera_status.emit("reconnecting")
    assert "Reconnecting" in cam.quality_label.text() and not cam.isComplete()
    workers[0].camera_status.emit("unavailable")
    assert "Camera unavailable" in cam.quality_label.text()


def test_reject_while_login_blocked_ignores_late_result(qtbot, monkeypatch):
    from moodmusic.ui import async_util
    gate = threading.Event()

    def login(cid, cancel=None):
        gate.wait(5)
    w, s, _, _ = make(qtbot, monkeypatch, login_fn=login)
    page = w.page(wiz.PAGE_SPOTIFY)
    page.client_edit.setText("abc")
    page.start_login()
    w.reject()
    gate.set()
    qtbot.waitUntil(lambda: not async_util._LIVE, timeout=3000)
    qtbot.wait(50)
    assert s.spotify_client_id == "" and not page.isComplete()


def test_source_load_error_offers_liked_songs_and_retry(qtbot, monkeypatch):
    calls = []

    def pl():
        calls.append(1)
        if len(calls) == 1:
            raise SpotifyError("x")
        return [("p1", "Mix", 3)]
    w, s, _, _ = make(qtbot, monkeypatch)
    src = wiz.SourcePage(s, pl)
    qtbot.addWidget(src)
    src.initializePage()
    qtbot.waitUntil(lambda: src.list.count() == 1, timeout=3000)
    assert src.isComplete() and src.selected_id() is None
    assert not src.retry_button.isHidden()
    src.load()
    qtbot.waitUntil(lambda: src.list.count() == 2, timeout=3000)


def test_accept_without_selection_does_nothing(qtbot, monkeypatch):
    w, s, saved, _ = make(qtbot, monkeypatch)
    w.accept()
    assert not s.setup_complete and saved == []


def test_login_timeout_message_and_retry(qtbot, monkeypatch):
    from moodmusic.spotify.auth import LoginTimeout
    calls = []

    def login(cid, cancel=None):
        calls.append(cid)
        if len(calls) == 1:
            raise LoginTimeout("x")
    w, *_ = make(qtbot, monkeypatch, login_fn=login)
    page = w.page(wiz.PAGE_SPOTIFY)
    page.client_edit.setText("abc")
    page.start_login()
    qtbot.waitUntil(lambda: "Didn't hear back" in page.status.text(), timeout=3000)
    assert page.status.text() == ("Didn't hear back from Spotify. Check the redirect URI in "
                                  "your Spotify app settings, then try again.")
    assert page.login_button.isEnabled() and page.cancel_button.isHidden()
    page.start_login()
    qtbot.waitUntil(page.isComplete, timeout=3000)


def test_closing_wizard_cancels_waiting_login(qtbot, monkeypatch):
    from moodmusic.ui import async_util
    cancels = []

    def login(cid, cancel=None):
        cancels.append(cancel)
        cancel.wait(5)
    w, s, _, _ = make(qtbot, monkeypatch, login_fn=login)
    page = w.page(wiz.PAGE_SPOTIFY)
    page.client_edit.setText("abc")
    page.start_login()
    assert not page.cancel_button.isHidden()
    qtbot.waitUntil(lambda: bool(cancels), timeout=3000)
    w.reject()
    assert cancels[0].is_set()
    qtbot.waitUntil(lambda: not async_util._LIVE, timeout=3000)
    assert not page.isComplete()
