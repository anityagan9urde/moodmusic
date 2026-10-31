"""Mood -> music orchestration. Pure logic, no Qt; call only from one thread.

on_mood() only records the latest mood (it runs for every camera frame); all Spotify I/O
happens in tick() and in explicit user actions. Nothing here ever sleeps.
Status: "ok" with an empty message when everything is fine.
"""
from __future__ import annotations

import functools
import logging
import random
from datetime import datetime
from collections.abc import Callable
from dataclasses import dataclass, replace

from moodmusic.app.playback_state import RateLimit, UserPause
from moodmusic.config import Settings
from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.intent import Intent, Mode, intent_for
from moodmusic.mood.states import FaceState
from moodmusic.mood.tracker import FaceMood
from moodmusic.music.selector import Pick, SongSelector
from moodmusic.spotify.client import (
    AuthRequired, Device, NoActiveDevice, NotPremium, PlaybackInfo, RateLimited, SpotifyError,
    SpotifyService, SpotifyUnavailable)
from moodmusic.vision.types import QualityReport

log = logging.getLogger(__name__)

HISTORY_SECONDS = 3600
HISTORY_STEP_S = 5  # at most one history point per 5 s
NEAR_END_MS = 3000
STALE_TICKS = 3
NO_DEVICE = "Open Spotify on any device"
CHOOSE_DEVICE = "Choose a Spotify device"
AUTH_EXPIRED = "Spotify login expired. Please log in again"
SLOW_DOWN = "Spotify asked us to slow down. Retrying…"
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
                 force_mood: Callable[[FaceState], None] | None = None,
                 hour_fn: Callable[[], int] | None = None) -> None:
        self.service = service
        self.selector = selector
        self.settings = settings
        self._clock = clock
        self._rng = rng
        self._force_mood = force_mood
        self._hour = hour_fn or (lambda: datetime.now().hour)
        self.listeners: list[Callable[[], None]] = []
        self.history: list[tuple[float, float, float]] = []
        self.current_pick: Pick | None = None
        self._mode = Mode(settings.mode)
        self._enabled = True
        self._mood: FaceMood | None = None
        self._quality = QualityReport(True)
        self._handled_state: FaceState | None = None  # face state we last acted on
        self._lift_state: FaceState | None = None  # state the lift steps belong to
        self._lift_step = 0
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
        self._user_pause = UserPause(NEAR_END_MS)
        self._rate_limit = RateLimit(clock)
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

    def set_service(self, service: SpotifyService) -> None:
        """Swap the Spotify client (after login, logout or a Client ID change)."""
        self.service = service
        self._rate_limit.reset()
        self._err = None
        self._notify()

    def _call(self, fn, *args):
        """Run a Spotify call; on SpotifyError set status and return _FAIL.

        While Spotify's Retry-After deadline is pending, nothing is sent at all.
        """
        if self._rate_limit.blocked():
            return _FAIL
        name = getattr(fn, "__name__", "call")
        before = self._err
        try:
            result = self._logged_call(name, fn, args)
        except RateLimited as exc:
            self._rate_limit.hit(exc.retry_after)
            self._err = EngineStatus("warning", SLOW_DOWN)
        except AuthRequired:
            self._err = EngineStatus("error", AUTH_EXPIRED)
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
            self._log_status_change(before)
            return result
        self._log_status_change(before)
        return _FAIL

    def _logged_call(self, name: str, fn, args):
        """Diagnostics: every Spotify command, and playback only when it changes."""
        try:
            result = fn(*args)
        except SpotifyError as exc:
            log.info("spotify %s%s -> %s: %s", name, args, type(exc).__name__, exc)
            raise
        if name == "playback":
            summary = None if result is None else (
                result.uri, result.device_id, result.is_playing)
            if summary != getattr(self, "_last_pb_summary", "unset"):
                self._last_pb_summary = summary
                log.info("spotify playback now: %s", summary)
        else:
            log.info("spotify %s%s -> ok%s", name, args,
                     f" {result}" if name == "devices" else "")
        return result

    def _log_status_change(self, before: EngineStatus | None) -> None:
        if self._err != before:
            log.info("engine status: %s", self._err or "ok")

    # ---- inputs -------------------------------------------------------
    def on_mood(self, state: FaceMood) -> None:
        """Called for every camera frame: record only (no Spotify I/O, see tick())."""
        try:
            if state.state != self._lift_state:  # any state change restarts the lift
                self._lift_state, self._lift_step = state.state, 0
            self._mood = state
            now = self._clock()
            if self.history and now - self.history[-1][0] < HISTORY_STEP_S:
                return
            self.history.append((now, state.valence, state.arousal))
            while self.history and now - self.history[0][0] > HISTORY_SECONDS:
                self.history.pop(0)
        except Exception:
            log.exception("Engine.on_mood failed")
            return
        self._notify()  # at most once per HISTORY_STEP_S

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
                    self._user_pause.resumed()
        elif self._face:
            self._face, self._face_lost_at = False, self._clock()

    @_public
    def set_mode(self, mode: Mode) -> None:
        self._mode = mode

    @_public
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @_public
    def not_how_i_feel(self, state: FaceState) -> None:
        if self._force_mood is not None:
            self._force_mood(state)

    # ---- periodic -----------------------------------------------------
    @_public
    def tick(self) -> None:
        if not self._enabled:
            return
        pb = self._call(self.service.playback)
        if pb is _FAIL:
            return
        if pb is not None:
            self._device_id = None  # a device is active: never pull playback away from it
        if self._paused_by_us:
            if self._face:  # retry a failed resume; honour a manual resume in Spotify
                if pb is not None and pb.is_playing:
                    self._paused_by_us = False
                elif self._call(self.service.resume) is not _FAIL:
                    self._paused_by_us = False
                    self._user_pause.resumed(grace=2)  # this tick and the next
                    if pb is not None:  # pb predates our resume
                        pb = replace(pb, is_playing=True)
            if self._paused_by_us:
                return
        if self._check_away(pb):
            return
        ours = (pb is not None and pb.uri == self._last_uri and self._manual_uri is None
                and self.current_pick is not None and pb.uri == self.current_pick.song.uri)
        self._user_pause.observe(pb, ours, self._seen)
        self._follow_playback(pb)
        self._apply_mood(pb)

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
            if self._stale_ticks > 0:  # just played: give Spotify time to report it
                self._stale_ticks -= 1
                return
            if self._last_uri is not None and self._can_act():
                self._manual_uri = None
                self._play_next()
            return
        if pb.uri is None:
            return
        if pb.uri == self._stale_uri and self._stale_ticks > 0:
            self._stale_ticks -= 1  # Spotify has not caught up with our play() yet
            return
        self._stale_uri, self._stale_ticks = None, 0
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
                self.selector.mark_played(pb.uri, self._clock())
            elif self.current_pick is not None and pb.uri == self.current_pick.song.uri:
                pass
            elif prev is not None and ours_prev and near_end and seen[0] == prev:
                self._manual_uri = None  # previous song ended: take over again
                if self._can_act():
                    self._play_next()
            elif pb.is_playing:
                log.info("engine: user is playing %s on device %s - backing off", pb.uri,
                         pb.device_id)
                self._manual_uri, self.current_pick, self._queued = pb.uri, None, None
        elif not pb.is_playing:
            reset = near_end and seen[0] == pb.uri and pb.progress_ms < seen[1]
            at_end = pb.duration_ms > 0 and pb.duration_ms - pb.progress_ms <= NEAR_END_MS
            if (reset or at_end) and self._can_act():  # stopped after finishing
                self._manual_uri = None
                self._play_next()
        elif (self._queued is None and self._manual_uri is None and self.current_pick is not None
              and not self._user_pause.active and pb.uri == self.current_pick.song.uri
              and pb.duration_ms - pb.progress_ms <= NEAR_END_MS):
            pick = self._choose()
            if pick is not None and self._call(self.service.queue, pick.song.uri) is not _FAIL:
                self._queued = pick
                self._ours[pick.song.uri] = pick

    # ---- decisions ----------------------------------------------------
    def _can_act(self) -> bool:
        return (self._enabled and self._mood is not None and self._quality.ok and self._face
                and not self._paused_by_us and not self._user_pause.active)

    def _intent(self, mood: FaceMood) -> Intent:
        """Music for the current state; lift steps restart whenever the state changes."""
        if mood.state != self._lift_state:
            self._lift_state, self._lift_step = mood.state, 0
        intent = intent_for(mood.state, self._mode, self._lift_step, self._hour(), self._rng)
        self._target = intent.groups[0]
        return intent

    def _pick_for(self, mood: FaceMood, intent: Intent) -> Pick | None:
        pick = self.selector.pick(intent.groups, mood, fresh=intent.fresh, now=self._clock())
        if pick is not None and intent.note:
            pick.reason += " — " + intent.note
        return pick

    def _choose(self) -> Pick | None:
        mood = self._mood
        if mood is None:
            if self.current_pick is None:
                return None
            mood = FaceMood()
        intent = self._intent(mood)
        pick = self._pick_for(mood, intent)
        if pick is not None and intent.lifting:
            self._lift_step += 1  # one lift step per song
        return pick

    def _play_next(self) -> bool:
        pick = self._choose()
        log.info("engine: play next -> %s (target %s, device %s)",
                 pick.song.uri if pick else None, self._target, self._device_id)
        if pick is None or not self._start(pick.song.uri):
            return False
        self._user_pause.resumed()
        self._stale_uri = self._last_uri if self._last_uri != pick.song.uri else None
        self._stale_ticks = STALE_TICKS
        self._last_uri = pick.song.uri
        self.current_pick, self._queued, self._manual_uri = pick, None, None
        self._seen = None
        self._handled_state = self._mood.state if self._mood else None
        self.selector.mark_played(pick.song.uri, self._clock())
        return True

    def _start(self, uri: str) -> bool:
        """play() a song; on NoActiveDevice fall back to the only available device.

        A device id is only passed while no device is active (chosen or fallback device);
        tick() forgets it once playback reports an active device.
        """
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
        pb = self._call(self.service.playback)
        if pb is not _FAIL and pb is None and self.current_pick is not None and self._can_act():
            self._play_next()  # nothing active: start our flow on the chosen device now
        elif pb is not _FAIL:
            self._apply_mood(pb)

    def _apply_mood(self, pb: PlaybackInfo | None) -> None:
        """Act on the latest mood. `pb` is this tick's playback (may predate our own play)."""
        if not self._can_act() or self._manual_uri is not None:
            return
        mood = self._mood
        if self.current_pick is None:
            if pb is None or not pb.is_playing:  # never override music the user started
                self._play_next()
            return
        if mood.state == self._handled_state:
            return
        intent = self._intent(mood)
        if self.current_pick.group in intent.groups and not intent.fresh:
            self._handled_state = mood.state  # what's playing already fits
        elif self._mode_immediate():
            self._play_next()
        elif self._queued is None:
            pick = self._pick_for(mood, intent)
            if pick is not None and self._call(self.service.queue, pick.song.uri) is not _FAIL:
                self._queued, self._handled_state = pick, mood.state
                self._ours[pick.song.uri] = pick
                if intent.lifting:
                    self._lift_step += 1
        else:
            self._handled_state = mood.state

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
            if self._call(self.service.pause) is not _FAIL:
                self._user_pause.paused(pb.progress_ms)
        elif self._call(self.service.resume) is not _FAIL:
            self._paused_by_us = False
            self._user_pause.resumed()

    @_public
    def wrong_vibe(self, new_group: MoodGroup) -> None:
        pick = self.current_pick
        if pick is None:
            return
        self.selector.library.set_group(pick.song.uri, new_group, by_user=True)
        target = self._target if self._target is not None else pick.group
        if new_group != target:
            self._play_next()
