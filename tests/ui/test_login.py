import threading

from moodmusic.app.engine import EngineStatus
from moodmusic.config import Settings
from moodmusic.spotify import auth
from moodmusic.ui import async_util
from moodmusic.ui import login as lg
from moodmusic.ui import settings_dialog as sd

AUTH = "Spotify login expired. Please log in again"


def controller(qtbot, login_fn, cid="cid"):
    got = {"success": 0, "notes": []}

    def ok():
        got["success"] += 1

    c = lg.LoginController(lambda: cid, ok, lambda t, m: got["notes"].append(m),
                           login_fn=login_fn)
    return c, got


def test_login_success_rebuilds_and_notifies(qtbot):
    seen = []
    c, got = controller(qtbot, lambda cid, cancel: seen.append((cid, cancel)))
    c.start()
    assert c.dialog is not None and c.dialog.isVisible()
    qtbot.waitUntil(lambda: got["success"] == 1, timeout=3000)
    assert seen[0][0] == "cid" and isinstance(seen[0][1], threading.Event)
    assert not c.is_running() and c.dialog is None
    assert got["notes"] == ["Logged in to Spotify."]


def test_login_timeout_shows_redirect_hint(qtbot):
    def boom(cid, cancel):
        raise auth.LoginTimeout("x")
    c, got = controller(qtbot, boom)
    c.start()
    qtbot.waitUntil(lambda: bool(got["notes"]), timeout=3000)
    assert got["notes"] == [lg.TIMEOUT_TEXT] and got["success"] == 0
    assert "redirect URI" in lg.TIMEOUT_TEXT


def test_cancel_abandons_login_and_ignores_late_result(qtbot):
    gate = threading.Event()
    cancels = []

    def wait(cid, cancel):
        cancels.append(cancel)
        cancel.wait(5)
        gate.wait(5)
    c, got = controller(qtbot, wait)
    c.start()
    c.start()  # a second request only raises the dialog
    qtbot.waitUntil(lambda: bool(cancels), timeout=3000)
    assert len(cancels) == 1
    c.dialog.cancel_button.click()
    assert cancels[0].is_set() and not c.is_running() and c.dialog is None
    gate.set()
    qtbot.waitUntil(lambda: not async_util._LIVE, timeout=3000)
    qtbot.wait(50)
    assert got["success"] == 0 and got["notes"] == []


def test_no_client_id_asks_for_settings(qtbot):
    calls = []
    c, got = controller(qtbot, lambda cid, cancel: calls.append(cid), cid=" ")
    c.start()
    assert not calls and "Client ID" in got["notes"][0] and not c.is_running()


def test_login_button_shown_only_when_login_expired(qtbot, engine, worker):
    from moodmusic.ui.dashboard import Dashboard
    from moodmusic.ui.widget import MoodWidget
    for cls in (MoodWidget, Dashboard):
        view = cls(engine, worker)
        qtbot.addWidget(view)
        requests = []
        view.login_requested.connect(lambda: requests.append(1))
        engine.status = EngineStatus("ok", "")
        view.refresh()
        assert view.login_btn.isHidden()
        engine.status = EngineStatus("error", AUTH)
        view.refresh()
        assert not view.login_btn.isHidden()
        view.login_btn.click()
        assert requests == [1]


def test_tray_has_login_action(qtbot, engine):
    from moodmusic.ui.tray import Tray

    class V:
        current = "simple"

        def show_view(self, n):
            pass

        def toggle(self):
            pass
    logins = []
    tray = Tray(engine, V(), lambda: None, lambda: None, on_login=lambda: logins.append(1))
    tray.login_action.trigger()
    assert logins == [1] and tray.login_action.text() == "Log in to Spotify"


class W:
    def __init__(self):
        self.calls = []

    def set_hold_seconds(self, s):
        self.calls.append(s)


def settings_dialog(qtbot, monkeypatch, s, hook):
    monkeypatch.setattr(sd, "save_settings", lambda s: None)
    monkeypatch.setattr(sd, "logout_spotify", lambda: None)
    d = sd.SettingsDialog(s, object(), W(), None, playlists_fn=lambda: [],
                          cameras_fn=lambda: [0], on_spotify_changed=hook)
    qtbot.addWidget(d)
    return d


def test_settings_client_id_change_and_logout_rebuild_service(qtbot, monkeypatch):
    rebuilt = []
    s = Settings(spotify_client_id="old")
    d = settings_dialog(qtbot, monkeypatch, s, lambda: rebuilt.append(s.spotify_client_id))
    d.save()
    assert rebuilt == []  # unchanged Client ID: no rebuild
    d.client_id.setText("new")
    d.save()
    assert rebuilt == ["new"]
    d.logout_button.click()
    assert rebuilt == ["new", "new"] and "Log in to Spotify" in d.note.text()


def test_settings_keeps_saved_camera_even_if_probe_misses_it(qtbot, monkeypatch):
    s = Settings(camera_index=3)
    d = settings_dialog(qtbot, monkeypatch, s, None)
    qtbot.waitUntil(lambda: d.camera.count() == 2, timeout=3000)
    assert [d.camera.itemData(i) for i in range(d.camera.count())] == [0, 3]
    assert d.camera.currentData() == 3
    d.save()
    assert s.camera_index == 3


def test_runtime_clients_are_non_interactive():
    from moodmusic.spotify.client import make_spotify
    from moodmusic.ui.main import build_scanner, make_engine_service
    assert isinstance(make_spotify("cid").auth_manager, auth.RuntimePKCE)
    svc = make_engine_service("cid")
    assert isinstance(svc.sp.auth_manager, auth.RuntimePKCE) and svc._retry_429 is False
    scanner = build_scanner(Settings(spotify_client_id="cid"), library=None)
    assert isinstance(scanner._service.sp.auth_manager, auth.RuntimePKCE)
