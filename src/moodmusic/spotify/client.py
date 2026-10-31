"""Resilient wrapper around spotipy. The only module that talks to Spotify."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import requests
import spotipy
from spotipy.exceptions import SpotifyException, SpotifyOauthError

from moodmusic.spotify.auth import KeyringCacheHandler, make_auth_manager

log = logging.getLogger(__name__)

MAX_RETRY_AFTER_S = 10  # longest sleep when retrying a 429 on a background thread
RATE_LIMIT_DEFAULT_S = 5  # RateLimited.retry_after when Spotify sends no Retry-After
RATE_LIMIT_MAX_S = 60


class SpotifyError(Exception):
    """Generic Spotify failure. Messages never contain tokens."""


class AuthRequired(SpotifyError):
    """Login expired/revoked/denied; the user must log in again."""


class NotPremium(SpotifyError):
    pass


class NoActiveDevice(SpotifyError):
    pass


class SpotifyUnavailable(SpotifyError):
    pass


class RateLimited(SpotifyUnavailable):
    """HTTP 429. `retry_after` is how many seconds to wait before calling again."""

    def __init__(self, message: str = "Spotify asked us to slow down",
                 retry_after: float = RATE_LIMIT_DEFAULT_S) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class PlaybackInfo:
    uri: str | None
    progress_ms: int
    duration_ms: int
    is_playing: bool
    device_id: str | None


@dataclass(frozen=True)
class Device:
    id: str | None
    name: str
    type: str
    is_active: bool


def make_spotify(client_id: str, auth_manager=None) -> spotipy.Spotify:
    """Spotify client with all spotipy-level retries disabled; _call owns retry policy.

    A plain requests.Session is passed so spotipy's urllib3 Retry (whose default
    status_forcelist turns 5xx into a headerless 429) is never installed.
    """
    # Bearer tokens appear in spotipy's DEBUG logs; never allow that.
    logging.getLogger("spotipy").setLevel(logging.WARNING)
    return spotipy.Spotify(
        auth_manager=auth_manager or make_auth_manager(client_id),
        requests_session=requests.Session(),
        requests_timeout=10,
        retries=0,
        status_retries=0,
    )


def _retry_after(e: SpotifyException, default: int = 1, cap: int = MAX_RETRY_AFTER_S) -> int:
    raw = (e.headers or {}).get("Retry-After", default)
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        val = default
    return max(0, min(val, cap))


class SpotifyService:
    """retry_429=True (background threads): sleep Retry-After once and retry.
    retry_429=False (GUI thread): never sleep; raise RateLimited instead."""

    def __init__(self, sp: spotipy.Spotify, sleep: Callable[[float], None] = time.sleep,
                 retry_429: bool = True):
        self.sp = sp
        self._sleep = sleep
        self._retry_429 = retry_429

    # ---- error handling -------------------------------------------------
    @staticmethod
    def _map(e: SpotifyException) -> SpotifyError:
        status = e.http_status
        msg = str(e.msg or "")
        reason = str(e.reason or "")
        if status == 404 and (reason == "NO_ACTIVE_DEVICE" or "No active device" in msg):
            return NoActiveDevice("No active Spotify device")
        if status == 403 and (reason == "PREMIUM_REQUIRED" or "Premium" in msg):
            return NotPremium("Spotify Premium is required")
        if status == 429:
            return RateLimited(retry_after=_retry_after(e, RATE_LIMIT_DEFAULT_S, RATE_LIMIT_MAX_S))
        if isinstance(status, int) and status >= 500:
            return SpotifyUnavailable(f"Spotify is unavailable (HTTP {status})")
        return SpotifyError(f"Spotify request failed (HTTP {status})")

    def _clear_token(self) -> None:
        try:
            handler = getattr(getattr(self.sp, "auth_manager", None), "cache_handler", None)
            if isinstance(handler, KeyringCacheHandler):
                handler.clear()
        except Exception as e:  # never let cleanup mask the real error
            log.warning("Could not clear cached token: %s", type(e).__name__)

    def _call(self, fn, *args, **kwargs):
        retried = False
        while True:
            try:
                return fn(*args, **kwargs)
            except SpotifyOauthError:  # includes SpotifyStateError
                self._clear_token()
                raise AuthRequired("Spotify login expired. Please log in again") from None
            except requests.RequestException as e:
                raise SpotifyUnavailable("Cannot reach Spotify") from e
            except SpotifyException as e:
                if not retried and e.http_status == 401:
                    retried = True
                    log.info("Spotify 401; retrying once")
                    continue
                if not retried and e.http_status == 429 and self._retry_429:
                    retried = True
                    self._sleep(_retry_after(e))
                    continue
                raise self._map(e) from None

    # ---- queries --------------------------------------------------------
    def check_premium(self) -> None:
        me = self._call(self.sp.me)
        if (me or {}).get("product") != "premium":
            raise NotPremium("Spotify Premium is required")

    def _pages(self, first: dict | None) -> Iterator[dict]:
        page = first
        while page:
            yield page
            page = self._call(self.sp.next, page) if page.get("next") else None

    def playlists(self) -> list[tuple[str, str, int]]:
        first = self._call(self.sp.current_user_playlists, limit=50)
        out = []
        for page in self._pages(first):
            for p in page.get("items") or []:
                if not p:
                    continue
                total = (p.get("tracks") or {}).get("total", 0)
                out.append((p["id"], p.get("name", ""), total))
        return out

    def iter_source_tracks(
        self, playlist_id: str | None
    ) -> Iterator[tuple[str, str, str, str | None]]:
        """Yield (uri, title, "A, B", art_url). Liked Songs when playlist_id is None.

        art_url is the first album image (Spotify lists the largest first).
        """
        if playlist_id is None:
            first = self._call(self.sp.current_user_saved_tracks, limit=50)
        else:
            first = self._call(
                self.sp.playlist_items, playlist_id, limit=50, additional_types=("track",)
            )
        for page in self._pages(first):
            for item in page.get("items") or []:
                t = (item or {}).get("track")
                if not t or t.get("is_local") or t.get("type") != "track" or not t.get("uri"):
                    continue
                artists = ", ".join(a.get("name", "") for a in t.get("artists") or [])
                images = (t.get("album") or {}).get("images") or []
                art = images[0].get("url") if images else None
                yield t["uri"], t.get("name", ""), artists, art

    def devices(self) -> list[Device]:
        r = self._call(self.sp.devices) or {}
        return [
            Device(d.get("id"), d.get("name", ""), d.get("type", ""), bool(d.get("is_active")))
            for d in r.get("devices") or []
        ]

    def playback(self) -> PlaybackInfo | None:
        r = self._call(self.sp.current_playback)
        if not r:
            return None
        item = r.get("item") or {}
        return PlaybackInfo(
            uri=item.get("uri"),
            progress_ms=r.get("progress_ms") or 0,
            duration_ms=item.get("duration_ms") or 0,
            is_playing=bool(r.get("is_playing")),
            device_id=(r.get("device") or {}).get("id"),
        )

    # ---- commands -------------------------------------------------------
    def play(self, uri: str, device_id: str | None = None) -> None:
        self._call(self.sp.start_playback, device_id=device_id, uris=[uri])

    def queue(self, uri: str) -> None:
        self._call(self.sp.add_to_queue, uri, device_id=None)

    def pause(self) -> None:
        self._call(self.sp.pause_playback)

    def resume(self) -> None:
        self._call(self.sp.start_playback)

    def next(self) -> None:
        self._call(self.sp.next_track)

    def previous(self) -> None:
        self._call(self.sp.previous_track)
