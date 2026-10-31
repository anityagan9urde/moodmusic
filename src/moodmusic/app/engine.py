"""Mood -> music orchestration. Pure logic, no Qt; call only from one thread.

Status: "ok" with an empty message when everything is fine.
"""
from __future__ import annotations

import functools
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass

from moodmusic.config import Settings
from moodmusic.mood.groups import Mode, MoodGroup, target_group
from moodmusic.mood.smoother import MoodState
from moodmusic.music.selector import Pick, SongSelector
from moodmusic.spotify.client import (
    AuthRequired, Device, NoActiveDevice, NotPremium, PlaybackInfo, SpotifyError, SpotifyService,
    SpotifyUnavailable)
from moodmusic.vision.types import QualityReport

log = logging.getLogger(__name__)

HISTORY_SECONDS = 3600
NEAR_END_MS = 3000
STALE_TICKS = 3
NO_DEVICE = "Open Spotify on any device"
CHOOSE_DEVICE = "Choose a Spotify device"
_FAIL = object()  # sentinel: a Spotify call failed (status already updated)


@dataclass(frozen=True)
class EngineStatus:
    kind: str  # "ok" | "warning" | "error"
    message: str


def _public(fn):
    """Public entry point: never raises, notifies listeners afterwards."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
            self._crashed = False
        except Exception:
            log.exception("Engine.%s failed", fn.__name__)
            self._crashed = True
        self._notify()
    return wrapper


class Engine:
    def __init__(self, service: SpotifyService, selector: SongSelector, settings: Settings,
                 clock: Callable[[], float], rng: random.Random,
                 force_mood: Callable[[MoodGroup], None] | None = None) -> None:
        self.service = service
        self.selector = selector
        self.settings = settings
        self._clock = clock
        self._rng = rng
        self._force_mood = force_mood
        self.listeners: list[Callable[[], None]] = []
        self.history: list[tuple[float, float, float]] = []
        self.current_pick: Pick | None = None
        self._mode = Mode(settings.mode)
        self._enabled = True
        self._mood: MoodState | None = None
        self._quality = QualityReport(True)
        self._handled_group: MoodGroup | None = None  # mood group we last acted on
        self._queued: Pick | None = None
        self._ours: dict[str, Pick] = {}  # queued picks (incl. orphaned) expected to arrive
        self._seen: tuple[str, int, int] | None = None  # (uri, progress, duration) last tick
        self._target: MoodGroup | None = None
        self._device_id: str | None = None
        self._stale_ticks = 0
        self._last_uri: str | None = None
        self._stale_uri: str | None = None  # old uri Spotify may still report after play()
        self._manual_uri: str | None = None
        self._face = True
        self._face_lost_at: float | None = None
        self._away_handled = False
        self._paused_by_us = False
        self._err: EngineStatus | None = None
        self._crashed = False

    # ---- status -------------------------------------------------------
    @property
    def status(self) -> EngineStatus:
        if self._crashed:
            return EngineStatus("error", "Something went wrong. Retrying…")
        if self._err is not None:
            return self._err
        if not self._quality.ok:
            return EngineStatus("warning", self._quality.issue or "Poor image quality")
        try:
            sorted_any = any(g != MoodGroup.UNSORTED and n > 0
                             for g, n in self.selector.library.counts().items())
        except Exception:
            log.exception("Could not count songs")
            sorted_any = True
        if not sorted_any:
            return EngineStatus("warning", "No songs sorted yet. Scanning your playlist…")
        return EngineStatus("ok", "")

    def _notify(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:
                log.exception("Engine listener failed")

    def _call(self, fn, *args):
        """Run a Spotify call; on SpotifyError set status and return _FAIL."""
        try:
            result = fn(*args)
        except AuthRequired:
            self._err = EngineStatus("error", "Spotify login expired. Please log in again")
        except NotPremium:
            self._err = EngineStatus("error", "Spotify Premium is needed for playback control")
        except NoActiveDevice:
            self._err = EngineStatus("error", NO_DEVICE)
        except SpotifyUnavailable:
            self._err = EngineStatus("warning", "Can't reach Spotify. Retrying…")
        except SpotifyError as exc:
            self._err = EngineStatus("error", f"Spotify error: {exc}")
        else:
            sticky = self._err is not None and self._err.message in (NO_DEVICE, CHOOSE_DEVICE)
            if not (result is None and fn == self.service.playback and sticky):
                self._err = None
            return result
        return _FAIL

    # ---- inputs -------------------------------------------------------
    @_public
    def on_mood(self, state: MoodState) -> None:
        now = self._clock()
        self._mood = state
        self.history.append((now, state.valence, state.arousal))
        self.history = [h for h in self.history if now - h[0] <= HISTORY_SECONDS]
        self._apply_mood()

    @_public
    def on_quality(self, report: QualityReport) -> None:
        self._quality = report

    @_public
    def on_face_present(self, present: bool) -> None:
        if present:
            self._face, self._face_lost_at, self._away_handled = True, None, False
            if self._paused_by_us:
                if self._call(self.service.resume) is not _FAIL:
                    self._paused_by_us = False
        elif self._face:
            self._face, self._face_lost_at = False, self._clock()

    @_public
    def set_mode(self, mode: Mode) -> None:
        self._mode = mode

    @_public
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @_public
    def not_how_i_feel(self, group: MoodGroup) -> None:
        if self._force_mood is not None:
            self._force_mood(group)

    # ---- periodic -----------------------------------------------------
    @_public
    def tick(self) -> None:
        if not self._enabled:
            return
        pb = self._call(self.service.playback)
        if pb is _FAIL:
            return
        if self._paused_by_us:
            if self._face:  # retry a failed resume; honour a manual resume in Spotify
                if (pb is not None and pb.is_playing) or self._call(self.service.resume) is not _FAIL:
                    self._paused_by_us = False
            if self._paused_by_us:
                return
        if self._check_away(pb):
            return
        self._follow_playback(pb)
        self._apply_mood()

    def _check_away(self, pb: PlaybackInfo | None) -> bool:
        minutes = self.settings.away_pause_minutes
        if (self._face or self._face_lost_at is None or self._away_handled or minutes <= 0
                or self._clock() - self._face_lost_at < minutes * 60):
            return False
        if pb is not None and pb.is_playing:
            if self._call(self.service.pause) is _FAIL:
                return False
            self._paused_by_us = True
        self._away_handled = True
        return True

    def _follow_playback(self, pb: PlaybackInfo | None) -> None:
        if pb is None:  # Spotify closed or idle: keep trying to resume our own flow
            if self._last_uri is not None and self._can_act():
                self._manual_uri = None
                self._play_next()
            return
        if pb.uri is None:
            return
        if pb.uri == self._stale_uri and self._stale_ticks > 0:
            self._stale_ticks -= 1  # Spotify has not caught up with our play() yet
            return
        self._stale_uri = None
        seen, self._seen = self._seen, (pb.uri, pb.progress_ms, pb.duration_ms)
        near_end = seen is not None and seen[2] - seen[1] <= NEAR_END_MS
        if pb.uri != self._last_uri:
            prev, self._last_uri = self._last_uri, pb.uri
            ours_prev = self._manual_uri == prev or (
                self.current_pick is not None and self.current_pick.song.uri == prev)
            if pb.uri in self._ours:
                pick = self._ours.pop(pb.uri)
                self.current_pick, self._manual_uri = pick, None
                if self._queued is pick:
                    self._queued = None
                self.selector.mark_played(pb.uri)
            elif self.current_pick is not None and pb.uri == self.current_pick.song.uri:
                pass
            elif prev is not None and ours_prev and near_end and seen[0] == prev:
                self._manual_uri = None  # previous song ended: take over again
                if self._can_act():
                    self._play_next()
            elif pb.is_playing:
                self._manual_uri, self.current_pick, self._queued = pb.uri, None, None
        elif not pb.is_playing:
            reset = near_end and seen[0] == pb.uri and pb.progress_ms < seen[1]
            at_end = pb.duration_ms > 0 and pb.duration_ms - pb.progress_ms <= NEAR_END_MS
            if (reset or at_end) and self._can_act():  # stopped after finishing
                self._manual_uri = None
                self._play_next()
        elif (self._queued is None and self._manual_uri is None and self.current_pick is not None
              and pb.uri == self.current_pick.song.uri
              and pb.duration_ms - pb.progress_ms <= NEAR_END_MS):
            pick = self._choose()
            if pick is not None and self._call(self.service.queue, pick.song.uri) is not _FAIL:
                self._queued = pick
                self._ours[pick.song.uri] = pick

    # ---- decisions ----------------------------------------------------
    def _can_act(self) -> bool:
        return (self._enabled and self._mood is not None and self._quality.ok and self._face
                and not self._paused_by_us)

    def _choose(self) -> Pick | None:
        mood = self._mood
        if mood is None:
            if self.current_pick is None:
                return None
            mood = MoodState(self.current_pick.group)
        self._target = target_group(mood.group, self._mode, self._rng)
        return self.selector.pick(self._target, mood)

    def _play_next(self) -> bool:
        pick = self._choose()
        if pick is None or not self._start(pick.song.uri):
            return False
        self._stale_uri = self._last_uri if self._last_uri != pick.song.uri else None
        self._stale_ticks = STALE_TICKS
        self._last_uri = pick.song.uri
        self.current_pick, self._queued, self._manual_uri = pick, None, None
        self._seen = None
        self._handled_group = self._mood.group if self._mood else None
        self.selector.mark_played(pick.song.uri)
        return True

    def _start(self, uri: str) -> bool:
        """play() a song; on NoActiveDevice fall back to the only available device."""
        if self._call(self.service.play, uri, self._device_id) is not _FAIL:
            return True
        if self._err is None or self._err.message != NO_DEVICE:
            return False
        failed = self._err
        devices = self._call(self.service.devices)
        self._err = failed
        usable = [d for d in devices if d.id] if devices is not _FAIL else []
        if len(usable) > 1:
            self._err = EngineStatus("error", CHOOSE_DEVICE)
        elif len(usable) == 1 and self._call(self.service.play, uri, usable[0].id) is not _FAIL:
            self._device_id = usable[0].id
            return True
        return False

    def available_devices(self) -> list[Device]:
        try:
            devices = self._call(self.service.devices)
        except Exception:
            log.exception("Engine.available_devices failed")
            return []
        return [] if devices is _FAIL else [d for d in devices if d.id]

    @_public
    def set_device(self, device_id: str) -> None:
        self._device_id = device_id
        self._apply_mood()

    def _apply_mood(self) -> None:
        if not self._can_act() or self._manual_uri is not None:
            return
        mood = self._mood
        if self.current_pick is None:
            info = self._call(self.service.playback)
            if info is _FAIL or (info is not None and info.is_playing):
                return
            self._play_next()
            return
        if mood.group == self._handled_group:
            return
        pick_now = self.current_pick
        target = self._target = target_group(mood.group, self._mode, self._rng)
        if target == pick_now.group:
            self._handled_group = mood.group
        elif self._mode_immediate():
            self._play_next()
        elif self._queued is None:
            pick = self.selector.pick(target, mood)
            if pick is not None and self._call(self.service.queue, pick.song.uri) is not _FAIL:
                self._queued, self._handled_group = pick, mood.group
                self._ours[pick.song.uri] = pick
        else:
            self._handled_group = mood.group

    def _mode_immediate(self) -> bool:
        return self.settings.switch_mode == "immediate"

    # ---- user actions -------------------------------------------------
    @_public
    def skip(self) -> None:
        if self._mood is not None or self.current_pick is not None:
            self._play_next()

    @_public
    def previous(self) -> None:
        self._call(self.service.previous)

    @_public
    def toggle_pause(self) -> None:
        pb = self._call(self.service.playback)
        if pb is _FAIL:
            return
        if pb is not None and pb.is_playing:
            self._call(self.service.pause)
        else:
            if self._call(self.service.resume) is not _FAIL:
                self._paused_by_us = False

    @_public
    def wrong_vibe(self, new_group: MoodGroup) -> None:
        pick = self.current_pick
        if pick is None:
            return
        self.selector.library.set_group(pick.song.uri, new_group, by_user=True)
        target = self._target if self._target is not None else pick.group
        if new_group != target:
            self._play_next()
