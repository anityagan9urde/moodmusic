"""Small pieces of playback state used by the Engine (kept apart to keep engine.py focused)."""
from __future__ import annotations

from collections.abc import Callable

from moodmusic.spotify.client import PlaybackInfo

RATE_LIMIT_DEFAULT_S, RATE_LIMIT_MAX_S = 5, 60


class RateLimit:
    """Spotify's Retry-After deadline: no Spotify call at all until it has passed."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._until: float | None = None

    def blocked(self) -> bool:
        if self._until is None:
            return False
        if self._clock() < self._until:
            return True
        self._until = None
        return False

    def hit(self, retry_after: float | None) -> None:
        wait = retry_after if retry_after and retry_after > 0 else RATE_LIMIT_DEFAULT_S
        self._until = self._clock() + min(wait, RATE_LIMIT_MAX_S)

    def reset(self) -> None:
        self._until = None


class UserPause:
    """Whether the user paused our music (our pause button, or in Spotify).

    While active, mood-driven actions must do nothing; skip / wrong vibe still act.
    """

    def __init__(self, near_end_ms: int) -> None:
        self._near_end_ms = near_end_ms
        self.active = False
        self._at: int | None = None  # progress when the pause was seen
        self._grace = 0  # ticks to ignore is_playing: Spotify may not report our change yet

    def paused(self, progress_ms: int) -> None:
        """Our pause button paused playback."""
        self.active, self._at, self._grace = True, progress_ms, 1

    def resumed(self, grace: int = 1) -> None:
        """Playback was resumed or a new song started by us."""
        self.active, self._at, self._grace = False, None, grace

    def observe(self, pb: PlaybackInfo | None, ours: bool,
                seen: tuple[str, int, int] | None) -> None:
        """Called each tick with fresh playback; `ours` = pb is the song we picked."""
        if self._grace > 0:
            self._grace -= 1
            return
        if pb is None or pb.uri is None:
            return
        if pb.is_playing:
            self.active, self._at = False, None
            return
        near = self._near_end_ms
        at_end = pb.duration_ms > 0 and pb.duration_ms - pb.progress_ms <= near
        reset = (seen is not None and seen[0] == pb.uri and seen[2] - seen[1] <= near
                 and pb.progress_ms < seen[1])
        if self.active and pb.progress_ms != self._at and (at_end or reset):
            self.active, self._at = False, None  # it played on and finished
        elif ours and not self.active and not at_end and not reset:
            self.active, self._at = True, pb.progress_ms
