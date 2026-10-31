import json
import threading
import time
import webbrowser

import keyring
import keyring.backend
import keyring.errors
import pytest
import requests
import spotipy.oauth2

from moodmusic.spotify import auth
from moodmusic.spotify.client import AuthRequired, SpotifyService, make_spotify



class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.store[(service, username)]


KEY = ("moodmusic", "spotify_token")


@pytest.fixture
def mem_keyring():
    old = keyring.get_keyring()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    yield kr
    keyring.set_keyring(old)


@pytest.fixture
def no_browser(monkeypatch):
    """Fail loudly if anything tries to open a browser or the local login server."""
    used = []

    def browser(*a, **k):
        used.append("browser")
        raise AssertionError("browser opened")

    def server(*a, **k):
        used.append("server")
        raise AssertionError("local server started")

    monkeypatch.setattr(webbrowser, "open", browser)
    monkeypatch.setattr(spotipy.oauth2, "start_local_http_server", server)
    monkeypatch.setattr(auth, "start_local_http_server", server, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(
        AssertionError("prompted")))
    return used


def token(access="a1", refresh="r1", expires_in=3600):
    return {"access_token": access, "refresh_token": refresh, "scope": auth.SCOPES,
            "token_type": "Bearer", "expires_in": expires_in,
            "expires_at": int(time.time()) + expires_in}


def test_runtime_call_without_token_raises_auth_required_without_browser(
        mem_keyring, no_browser):
    svc = SpotifyService(make_spotify("cid"))
    with pytest.raises(AuthRequired):
        svc.playback()
    assert no_browser == []


def test_runtime_refresh_refused_raises_auth_required_without_browser(
        mem_keyring, no_browser, monkeypatch):
    mem_keyring.store[KEY] = json.dumps(token(expires_in=-100))
    am = auth.make_auth_manager("cid")

    class Resp:
        status_code = 400

        def json(self):
            return {"error": "invalid_grant"}

        def raise_for_status(self):
            raise requests.HTTPError(response=self)

    am._session = type("S", (), {"post": lambda self, *a, **k: Resp()})()
    with pytest.raises(AuthRequired):
        SpotifyService(make_spotify("cid", auth_manager=am)).playback()
    assert no_browser == []
    assert KEY not in mem_keyring.store  # refused token is cleared


class TokenServer:
    """Fake Spotify token endpoint that rotates refresh tokens (old one stops working)."""

    def __init__(self):
        self.valid = {"r1"}
        self.active = self.max_active = self.posts = 0
        self.lock = threading.Lock()
        self.n = 1

    def post(self, url, data=None, **kw):
        with self.lock:
            self.active += 1
            self.posts += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.2)
        with self.lock:
            self.active -= 1
            ok = data["refresh_token"] in self.valid
            if ok:
                self.valid.discard(data["refresh_token"])
                self.n += 1
                self.valid.add(f"r{self.n}")
                body = {"access_token": f"a{self.n}", "refresh_token": f"r{self.n}",
                        "scope": auth.SCOPES, "expires_in": 3600, "token_type": "Bearer"}
        class Resp:
            status_code = 200 if ok else 400

            def json(self):
                return body if ok else {"error": "invalid_grant"}

            def raise_for_status(self):
                if not ok:
                    raise requests.HTTPError(response=self)
        return Resp()


def test_concurrent_refreshes_are_serialised(mem_keyring, no_browser):
    mem_keyring.store[KEY] = json.dumps(token(expires_in=-100))
    srv = TokenServer()
    managers = [auth.make_auth_manager("cid"), auth.make_auth_manager("cid")]
    for am in managers:
        am._session = srv
    results, errors = [], []

    def use(am):
        try:
            results.append(am.get_access_token())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=use, args=(am,)) for am in managers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert errors == [] and srv.max_active == 1 and srv.posts == 1
    assert results == ["a2", "a2"]
    assert json.loads(mem_keyring.store[KEY])["refresh_token"] == "r2"


class FakeServer:
    def __init__(self):
        self.auth_code = self.error = None
        self.closed = False
        self.handled = 0
        self.timeout = None

    def handle_request(self):
        self.handled += 1
        time.sleep(0.01)

    def server_close(self):
        self.closed = True


def test_interactive_login_times_out_and_closes_server(mem_keyring, monkeypatch):
    srv = FakeServer()
    opened = []
    monkeypatch.setattr(auth, "start_local_http_server", lambda port: srv)
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    with pytest.raises(auth.LoginTimeout):
        auth.login_interactive("cid", timeout_s=0.1)
    assert srv.closed and srv.handled > 0 and len(opened) == 1
    assert srv.timeout is not None and srv.timeout <= 1
    assert "access_token" not in opened[0]
    # the port guard was released: a second attempt runs (and times out) again
    srv2 = FakeServer()
    monkeypatch.setattr(auth, "start_local_http_server", lambda port: srv2)
    with pytest.raises(auth.LoginTimeout):
        auth.login_interactive("cid", timeout_s=0.05)
    assert srv2.closed


def test_interactive_login_cancel_abandons_quickly(mem_keyring, monkeypatch):
    srv = FakeServer()
    monkeypatch.setattr(auth, "start_local_http_server", lambda port: srv)
    monkeypatch.setattr(webbrowser, "open", lambda url: None)
    cancel = threading.Event()
    cancel.set()
    started = time.monotonic()
    with pytest.raises(auth.LoginCancelled):
        auth.login_interactive("cid", timeout_s=60, cancel=cancel)
    assert time.monotonic() - started < 1 and srv.closed


def test_only_one_interactive_login_at_a_time(mem_keyring, monkeypatch):
    srv = FakeServer()
    monkeypatch.setattr(auth, "start_local_http_server", lambda port: srv)
    monkeypatch.setattr(webbrowser, "open", lambda url: None)
    cancel = threading.Event()
    t = threading.Thread(target=lambda: pytest.raises(
        auth.LoginCancelled, auth.login_interactive, "cid", 60, cancel))
    t.start()
    try:
        deadline = time.monotonic() + 2
        while srv.handled == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        with pytest.raises(auth.LoginInProgress):
            auth.login_interactive("cid", timeout_s=0.05)
    finally:
        cancel.set()
        t.join(3)
    assert not t.is_alive()


def test_interactive_login_stores_token(mem_keyring, monkeypatch):
    srv = FakeServer()
    srv.auth_code = "code123"
    monkeypatch.setattr(auth, "start_local_http_server", lambda port: srv)
    monkeypatch.setattr(webbrowser, "open", lambda url: None)

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "new", "refresh_token": "rr", "scope": auth.SCOPES,
                    "expires_in": 3600, "token_type": "Bearer"}

    monkeypatch.setattr(requests.Session, "post", lambda self, *a, **k: Resp())
    auth.login_interactive("cid", timeout_s=5)
    assert json.loads(mem_keyring.store[KEY])["access_token"] == "new" and srv.closed
