"""Spotify PKCE auth with tokens stored in the OS keyring.

Two kinds of auth manager:
- RuntimePKCE (used by the engine, the scanner and playlist loading) never opens a browser
  or a local server: no usable token -> LoginRequired.
- login_interactive() is the only way to log in (wizard / "Log in to Spotify"). It opens the
  browser and waits on 127.0.0.1:8765 with a timeout and a cancel flag, one login at a time.

TOKEN_LOCK serialises every token read-modify-write in the process, so the engine and the
scanner never refresh the same token concurrently.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import keyring
import keyring.errors
import spotipy
from spotipy.cache_handler import CacheHandler
from spotipy.exceptions import SpotifyOauthError, SpotifyStateError
from spotipy.oauth2 import start_local_http_server

log = logging.getLogger(__name__)

REDIRECT_URI = "http://127.0.0.1:8765/callback"
SCOPES = (
    "user-read-playback-state user-modify-playback-state "
    "user-read-currently-playing playlist-read-private "
    "playlist-read-collaborative user-library-read user-read-private"
)
KEYRING_SERVICE = "moodmusic"
KEYRING_USER = "spotify_token"
LOGIN_TIMEOUT_S = 180
POLL_S = 0.5  # how often a waiting login checks for cancel/timeout

TOKEN_LOCK = threading.RLock()
_LOGIN_LOCK = threading.Lock()  # one interactive login (port 8765) at a time


class LoginRequired(SpotifyOauthError):
    """No usable token; only an explicit interactive login can fix it."""


class LoginError(Exception):
    """Interactive login did not complete. Messages are safe to show to the user."""


class LoginTimeout(LoginError):
    pass


class LoginCancelled(LoginError):
    pass


class LoginInProgress(LoginError):
    pass


class KeyringCacheHandler(CacheHandler):
    """Stores the spotipy token dict as JSON in the OS keyring.

    Keyring failures never raise: they are logged and behave as "no token".
    """

    def __init__(self, service: str = KEYRING_SERVICE, username: str = KEYRING_USER):
        self.service = service
        self.username = username

    def get_cached_token(self) -> dict | None:
        with TOKEN_LOCK:
            try:
                raw = keyring.get_password(self.service, self.username)
            except keyring.errors.KeyringError as e:
                log.warning("Keyring read failed: %s", type(e).__name__)
                return None
        if not raw:
            return None
        try:
            token = json.loads(raw)
        except ValueError:
            log.warning("Cached Spotify token is corrupt; ignoring it")
            return None
        return token if isinstance(token, dict) else None

    def save_token_to_cache(self, token_info: dict) -> None:
        with TOKEN_LOCK:
            try:
                keyring.set_password(self.service, self.username, json.dumps(token_info))
            except keyring.errors.KeyringError as e:
                log.warning("Keyring write failed: %s", type(e).__name__)

    def clear(self) -> None:
        with TOKEN_LOCK:
            try:
                keyring.delete_password(self.service, self.username)
            except keyring.errors.PasswordDeleteError:
                pass  # nothing stored
            except keyring.errors.KeyringError as e:
                log.warning("Keyring delete failed: %s", type(e).__name__)


class RuntimePKCE(spotipy.SpotifyPKCE):
    """Uses and refreshes the cached token; never starts an interactive login."""

    def __init__(self, client_id: str, cache_handler: CacheHandler | None = None) -> None:
        super().__init__(client_id=client_id, redirect_uri=REDIRECT_URI, scope=SCOPES,
                         open_browser=False,
                         cache_handler=cache_handler or KeyringCacheHandler())

    def _usable(self, token) -> bool:
        return (isinstance(token, dict) and "access_token" in token and "scope" in token
                and self._is_scope_subset(self.scope, token["scope"]))

    def get_access_token(self, code=None, check_cache=True):
        with TOKEN_LOCK:
            cached = self.cache_handler.get_cached_token()
            if not self._usable(cached):
                raise LoginRequired("Not logged in to Spotify")
            if not self.is_token_expired(cached):
                return cached["access_token"]
            try:
                return self.refresh_access_token(cached["refresh_token"])["access_token"]
            except (SpotifyOauthError, KeyError, TypeError):
                # Re-read: if someone refreshed meanwhile, that token is good; keep it.
                now = self.cache_handler.get_cached_token()
                if self._usable(now) and now != cached and not self.is_token_expired(now):
                    return now["access_token"]
                if now == cached and hasattr(self.cache_handler, "clear"):
                    self.cache_handler.clear()
                log.info("Spotify token refresh was refused; a new login is needed")
                raise LoginRequired("Spotify login expired") from None

    def get_authorization_code(self, response=None):
        raise LoginRequired("Not logged in to Spotify")

    def _get_auth_response(self, open_browser=None):
        raise LoginRequired("Not logged in to Spotify")


class InteractivePKCE(spotipy.SpotifyPKCE):
    """Browser login whose local server has a timeout, can be cancelled, and is always closed."""

    def __init__(self, client_id: str, timeout_s: float = LOGIN_TIMEOUT_S,
                 cancel: threading.Event | None = None, clock=time.monotonic) -> None:
        super().__init__(client_id=client_id, redirect_uri=REDIRECT_URI, scope=SCOPES,
                         open_browser=True, cache_handler=KeyringCacheHandler())
        self._timeout_s, self._cancel, self._clock = timeout_s, cancel, clock

    def _get_auth_response_local_server(self, redirect_port):
        try:
            server = start_local_http_server(redirect_port)
        except OSError:
            raise LoginError(f"Port {redirect_port} is in use by another program (or another "
                             "Mood Music window). Close it during login, then try again.") from None
        try:
            server.timeout = POLL_S
            self._open_auth_url()
            deadline = self._clock() + self._timeout_s
            while server.auth_code is None and server.error is None:
                if self._cancel is not None and self._cancel.is_set():
                    raise LoginCancelled("Login cancelled")
                if self._clock() >= deadline:
                    raise LoginTimeout("Didn't hear back from Spotify")
                server.handle_request()
        finally:
            server.server_close()
        if self.state is not None and getattr(server, "state", None) != self.state:
            raise SpotifyStateError(self.state, getattr(server, "state", None))
        if server.auth_code is not None:
            return server.auth_code
        raise SpotifyOauthError("Spotify login was refused")


def login_interactive(client_id: str, timeout_s: float = LOGIN_TIMEOUT_S,
                      cancel: threading.Event | None = None) -> None:
    """Blocking browser login that stores the token. Call from a worker thread only."""
    if not _LOGIN_LOCK.acquire(blocking=False):
        raise LoginInProgress("A Spotify login is already waiting in your browser")
    try:
        InteractivePKCE(client_id, timeout_s, cancel).get_access_token(check_cache=False)
    finally:
        _LOGIN_LOCK.release()


def make_auth_manager(client_id: str) -> spotipy.SpotifyPKCE:
    """The runtime (non-interactive) auth manager."""
    return RuntimePKCE(client_id)
