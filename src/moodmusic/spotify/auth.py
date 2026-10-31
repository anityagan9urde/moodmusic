"""Spotify PKCE auth manager with tokens stored in the OS keyring."""
from __future__ import annotations

import json
import logging

import keyring
import keyring.errors
import spotipy
from spotipy.cache_handler import CacheHandler

log = logging.getLogger(__name__)

REDIRECT_URI = "http://127.0.0.1:8765/callback"
SCOPES = (
    "user-read-playback-state user-modify-playback-state "
    "user-read-currently-playing playlist-read-private "
    "playlist-read-collaborative user-library-read user-read-private"
)
KEYRING_SERVICE = "moodmusic"
KEYRING_USER = "spotify_token"


class KeyringCacheHandler(CacheHandler):
    """Stores the spotipy token dict as JSON in the OS keyring.

    Keyring failures never raise: they are logged and behave as "no token".
    """

    def __init__(self, service: str = KEYRING_SERVICE, username: str = KEYRING_USER):
        self.service = service
        self.username = username

    def get_cached_token(self) -> dict | None:
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
        try:
            keyring.set_password(self.service, self.username, json.dumps(token_info))
        except keyring.errors.KeyringError as e:
            log.warning("Keyring write failed: %s", type(e).__name__)

    def clear(self) -> None:
        try:
            keyring.delete_password(self.service, self.username)
        except keyring.errors.PasswordDeleteError:
            pass  # nothing stored
        except keyring.errors.KeyringError as e:
            log.warning("Keyring delete failed: %s", type(e).__name__)


def make_auth_manager(client_id: str) -> spotipy.SpotifyPKCE:
    return spotipy.SpotifyPKCE(
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        open_browser=True,
        cache_handler=KeyringCacheHandler(),
    )
