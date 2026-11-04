"""Minimal Last.fm client for top tags."""
from __future__ import annotations

import logging
import re
import time
from typing import Callable

import requests

log = logging.getLogger(__name__)

API_URL = "https://ws.audioscrobbler.com/2.0/"
TIMEOUT = 10
ATTEMPTS = 3
BACKOFF = (1, 2)

ERR_NOT_FOUND = 6
ERR_RATE_LIMIT = 29


class LastFmError(Exception):
    pass


_SUFFIXES = [
    re.compile(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]", re.I),
    re.compile(r"\s+-\s+(?:remaster(?:ed)?|live|radio edit|\d{4}\s+remaster).*$", re.I),
]


def clean_title(title: str) -> str:
    out = title
    for pat in _SUFFIXES:
        out = pat.sub("", out)
    return out.strip() or title.strip()


_KEY_PARAM = re.compile(r"(api_key=)[^&\s'\")]*", re.I)


class LastFmClient:
    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        min_interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def track_tags(self, artist: str, title: str) -> list[tuple[str, int]]:
        return self._tags("track.gettoptags", artist=artist, track=clean_title(title))

    def artist_tags(self, artist: str) -> list[tuple[str, int]]:
        return self._tags("artist.gettoptags", artist=artist)

    def _throttle(self) -> None:
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def _tags(self, method: str, **extra) -> list[tuple[str, int]]:
        params = {
            "method": method,
            "api_key": self.api_key,
            "autocorrect": 1,
            "format": "json",
            **extra,
        }
        data = self._request(params)
        if data is None:
            return []
        tags = (data.get("toptags") or {}).get("tag") or []
        if isinstance(tags, dict):
            tags = [tags]
        out: list[tuple[str, int]] = []
        for t in tags:
            try:
                out.append((str(t["name"]).strip().lower(), int(t.get("count", 0))))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def _scrub(self, text: str) -> str:
        text = _KEY_PARAM.sub(r"***", text)
        return text.replace(self.api_key, "***") if self.api_key else text

    def _request(self, params: dict) -> dict | None:
        last_err = "unknown error"
        for attempt in range(ATTEMPTS):
            if attempt:
                self._sleep(BACKOFF[attempt - 1])
            self._throttle()
            try:
                resp = self.session.get(API_URL, params=params, timeout=TIMEOUT)
            except requests.RequestException as e:
                last_err = f"connection error: {type(e).__name__}"
                continue
            status = resp.status_code
            if status == 429 or status >= 500:
                last_err = f"HTTP {status}"
                continue
            if status != 200:
                raise LastFmError(f"HTTP {status}")
            try:
                data = resp.json()
            except ValueError as e:
                raise LastFmError(self._scrub(f"invalid JSON: {e}")) from None
            if isinstance(data, dict) and "error" in data:
                code = data.get("error")
                if code == ERR_NOT_FOUND:
                    return None
                msg = data.get("message", "")
                if code == ERR_RATE_LIMIT:
                    last_err = f"rate limited: {msg}"
                    continue
                raise LastFmError(self._scrub(f"Last.fm error {code}: {msg}"))
            return data
        raise LastFmError(
            self._scrub(f"Last.fm request failed after {ATTEMPTS} attempts: {last_err}")
        )
