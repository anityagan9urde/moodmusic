import json

import keyring
import keyring.backend
import keyring.errors
import pytest
import requests
from spotipy.exceptions import SpotifyException

from moodmusic.spotify.auth import KeyringCacheHandler
from moodmusic.spotify.client import (
    NoActiveDevice,
    NotPremium,
    SpotifyError,
    SpotifyService,
    SpotifyUnavailable,
)


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


class BrokenKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def get_password(self, service, username):
        raise keyring.errors.KeyringError("x")

    def set_password(self, service, username, password):
        raise keyring.errors.KeyringError("x")

    def delete_password(self, service, username):
        raise keyring.errors.KeyringError("x")


@pytest.fixture
def mem_keyring():
    old = keyring.get_keyring()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    yield kr
    keyring.set_keyring(old)


def track(n, **kw):
    d = {"uri": f"spotify:track:{n}", "name": f"T{n}", "type": "track",
         "is_local": False,
         "artists": [{"name": "A"}, {"name": "B"}],
         "album": {"images": [{"url": f"http://img/{n}"}]}}
    d.update(kw)
    return d


class FakeSp:
    def __init__(self):
        self.pages = {}
        self.next_calls = 0

    def playlist_items(self, pid, **kw):
        return self.pages["first"]

    def current_user_saved_tracks(self, limit=50):
        return self.pages["first"]

    def next(self, page):
        self.next_calls += 1
        return self.pages.get(page.get("next"))


def svc(sp, sleeps=None):
    return SpotifyService(sp, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_iter_skips_local_episodes_and_none():
    sp = FakeSp()
    sp.pages["first"] = {"items": [
        {"track": track(1)},
        {"track": None},
        {"track": track(2, is_local=True)},
    ], "next": "p2"}
    sp.pages["p2"] = {"items": [
        {"track": track(3, type="episode")},
        {"track": track(4)},
    ], "next": None}
    out = list(svc(sp).iter_source_tracks("pl"))
    assert out == [("spotify:track:1", "T1", "A, B", "http://img/1"),
                   ("spotify:track:4", "T4", "A, B", "http://img/4")]
    assert sp.next_calls == 1


def test_iter_liked_songs_and_no_art():
    sp = FakeSp()
    sp.pages["first"] = {"items": [{"track": track(1, album={"images": []})}], "next": None}
    assert list(svc(sp).iter_source_tracks(None)) == [("spotify:track:1", "T1", "A, B", None)]


def test_no_active_device_raises():
    class Sp:
        def start_playback(self, **kw):
            raise SpotifyException(404, -1, "Player command failed: No active device found",
                                   reason="NO_ACTIVE_DEVICE")
    with pytest.raises(NoActiveDevice):
        svc(Sp()).play("spotify:track:1")


def test_401_retries_once_then_succeeds():
    calls = []

    class Sp:
        def pause_playback(self, device_id=None):
            calls.append(1)
            if len(calls) == 1:
                raise SpotifyException(401, -1, "expired")
    svc(Sp()).pause()
    assert len(calls) == 2


def test_401_twice_raises_spotify_error():
    class Sp:
        def pause_playback(self, device_id=None):
            raise SpotifyException(401, -1, "token abc123 bad")
    with pytest.raises(SpotifyError) as e:
        svc(Sp()).pause()
    assert "abc123" not in str(e.value)


def test_connection_error_raises_unavailable():
    class Sp:
        def devices(self):
            raise requests.ConnectionError("down")
    with pytest.raises(SpotifyUnavailable):
        svc(Sp()).devices()


def test_timeout_and_5xx_raise_unavailable():
    class Sp:
        def devices(self):
            raise requests.Timeout("slow")

        def current_playback(self):
            raise SpotifyException(503, -1, "oops")
    with pytest.raises(SpotifyUnavailable):
        svc(Sp()).devices()
    with pytest.raises(SpotifyUnavailable):
        svc(Sp()).playback()


def test_429_sleeps_retry_after_capped_and_retries():
    calls = []
    sleeps = []

    class Sp:
        def pause_playback(self, device_id=None):
            calls.append(1)
            if len(calls) == 1:
                raise SpotifyException(429, -1, "slow down", headers={"Retry-After": "99"})
    svc(Sp(), sleeps).pause()
    assert sleeps == [10] and len(calls) == 2


def test_429_default_sleep_is_one():
    calls = []
    sleeps = []

    class Sp:
        def pause_playback(self, device_id=None):
            calls.append(1)
            if len(calls) == 1:
                raise SpotifyException(429, -1, "slow down")
    svc(Sp(), sleeps).pause()
    assert sleeps == [1]


def test_not_premium_from_me():
    class Sp:
        def me(self):
            return {"product": "free"}
    with pytest.raises(NotPremium):
        svc(Sp()).check_premium()


def test_premium_ok():
    class Sp:
        def me(self):
            return {"product": "premium"}
    svc(Sp()).check_premium()


def test_403_premium_required_maps():
    class Sp:
        def start_playback(self, **kw):
            raise SpotifyException(403, -1, "Player command failed: Premium required",
                                   reason="PREMIUM_REQUIRED")
    with pytest.raises(NotPremium):
        svc(Sp()).play("u")


def test_other_error_is_spotify_error():
    class Sp:
        def pause_playback(self, device_id=None):
            raise SpotifyException(400, -1, "bad request")
    with pytest.raises(SpotifyError):
        svc(Sp()).pause()


def test_playback_none_and_parsed():
    class Sp:
        r = None

        def current_playback(self):
            return self.r
    sp = Sp()
    assert svc(sp).playback() is None
    sp.r = {"is_playing": True, "progress_ms": 5, "item": {"uri": "u", "duration_ms": 100},
            "device": {"id": "d1"}}
    p = svc(sp).playback()
    assert (p.uri, p.progress_ms, p.duration_ms, p.is_playing, p.device_id) == ("u", 5, 100, True, "d1")


def test_devices_playlists_and_commands():
    rec = []

    class Sp:
        def devices(self):
            return {"devices": [{"id": "d", "name": "PC", "type": "Computer", "is_active": True}]}

        def current_user_playlists(self, limit=50, offset=0):
            return {"items": [{"id": "p", "name": "N", "tracks": {"total": 3}}], "next": None}

        def next(self, page):
            return None

        def add_to_queue(self, uri, device_id=None):
            rec.append(("q", uri, device_id))

        def start_playback(self, device_id=None, uris=None):
            rec.append(("p", device_id, uris))

        def next_track(self, device_id=None):
            rec.append("n")

        def previous_track(self, device_id=None):
            rec.append("b")
    s = svc(Sp())
    d = s.devices()[0]
    assert (d.id, d.name, d.type, d.is_active) == ("d", "PC", "Computer", True)
    assert s.playlists() == [("p", "N", 3)]
    s.queue("u")
    s.play("u", "d")
    s.resume()
    s.next()
    s.previous()
    assert rec == [("q", "u", None), ("p", "d", ["u"]), ("p", None, None), "n", "b"]


def test_keyring_cache_roundtrip(mem_keyring):
    h = KeyringCacheHandler()
    assert h.get_cached_token() is None
    tok = {"access_token": "a", "refresh_token": "r", "expires_at": 1}
    h.save_token_to_cache(tok)
    assert json.loads(mem_keyring.store[("moodmusic", "spotify_token")]) == tok
    assert h.get_cached_token() == tok
    h.clear()
    assert h.get_cached_token() is None
    h.clear()  # idempotent


def test_keyring_corrupt_returns_none(mem_keyring):
    mem_keyring.store[("moodmusic", "spotify_token")] = "{not json"
    assert KeyringCacheHandler().get_cached_token() is None


def test_keyring_errors_do_not_crash():
    old = keyring.get_keyring()
    keyring.set_keyring(BrokenKeyring())
    try:
        h = KeyringCacheHandler()
        assert h.get_cached_token() is None
        h.save_token_to_cache({"a": 1})
        h.clear()
    finally:
        keyring.set_keyring(old)


def test_make_auth_manager_config(mem_keyring):
    from moodmusic.spotify.auth import REDIRECT_URI, SCOPES, make_auth_manager
    am = make_auth_manager("cid")
    assert am.redirect_uri == REDIRECT_URI == "http://127.0.0.1:8765/callback"
    assert "user-read-playback-state" in am.scope and "user-read-private" in am.scope
    assert isinstance(am.cache_handler, KeyringCacheHandler)
    assert SCOPES.count(" ") == 6


# ---- auth failures ---------------------------------------------------------
def test_oauth_errors_map_to_auth_required_and_clear_token(mem_keyring):
    from spotipy.exceptions import SpotifyOauthError, SpotifyStateError

    from moodmusic.spotify.client import AuthRequired
    for exc in (SpotifyOauthError("refresh token abc123 revoked"), SpotifyStateError("a", "b")):
        mem_keyring.store[("moodmusic", "spotify_token")] = "{}"

        class Sp:
            auth_manager = type("AM", (), {"cache_handler": KeyringCacheHandler()})()

            def devices(self):
                raise exc
        with pytest.raises(AuthRequired) as e:
            svc(Sp()).devices()
        assert "abc123" not in str(e.value)
        assert ("moodmusic", "spotify_token") not in mem_keyring.store


def test_other_request_exceptions_are_unavailable():
    class Sp:
        def devices(self):
            raise requests.exceptions.ChunkedEncodingError("cut")
    with pytest.raises(SpotifyUnavailable):
        svc(Sp()).devices()


# ---- real spotipy against a local stub server ------------------------------
@pytest.fixture
def stub_server():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    state = {"responses": [], "hits": 0}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            state["hits"] += 1
            code, headers, body = state["responses"].pop(0)
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}/"
    yield state
    srv.shutdown()
    srv.server_close()


class StaticAuth:
    def get_access_token(self, as_dict=False):
        return "static-token"


def real_service(state, sleeps):
    from moodmusic.spotify.client import make_spotify
    sp = make_spotify("cid", auth_manager=StaticAuth())
    sp.prefix = state["url"]
    return SpotifyService(sp, sleep=sleeps.append)


def test_real_spotipy_503_is_unavailable(stub_server):
    stub_server["responses"] = [(503, {"Retry-After": "7"}, b"{}")]
    sleeps = []
    with pytest.raises(SpotifyUnavailable):
        real_service(stub_server, sleeps).devices()
    assert sleeps == [] and stub_server["hits"] == 1


def test_real_spotipy_429_honours_retry_after(stub_server):
    stub_server["responses"] = [(429, {"Retry-After": "3"}, b"{}"),
                                (200, {"Content-Type": "application/json"},
                                 b'{"devices": []}')]
    sleeps = []
    assert real_service(stub_server, sleeps).devices() == []
    assert sleeps == [3] and stub_server["hits"] == 2
