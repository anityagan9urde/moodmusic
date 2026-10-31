import random

import pytest

from moodmusic.app.engine import Engine
from moodmusic.config import Settings
from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.states import FaceState
from moodmusic.mood.tracker import FaceMood
from moodmusic.music.library import Song, SongLibrary
from moodmusic.music.selector import SongSelector
from moodmusic.spotify.client import (
    AuthRequired, NoActiveDevice, NotPremium, Device, PlaybackInfo, SpotifyError, SpotifyUnavailable)
from moodmusic.vision.types import QualityReport


class FakeService:
    def __init__(self):
        self.calls = []
        self.pb = None
        self.devs = []
        self.fail = {}  # method -> list of exceptions raised one per call

    def _do(self, name, *args):
        self.calls.append((name, *args))
        errs = self.fail.get(name)
        if errs:
            raise errs.pop(0)

    def playback(self):
        self._do("playback")
        return self.pb

    def play(self, uri, device_id=None):
        self._do("play", uri, device_id)

    def devices(self):
        self._do("devices")
        return self.devs

    def queue(self, uri):
        self._do("queue", uri)

    def pause(self):
        self._do("pause")

    def resume(self):
        self._do("resume")

    def next(self):
        self._do("next")

    def previous(self):
        self._do("previous")

    def names(self, name):
        return [c[1:] for c in self.calls if c[0] == name]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def mk(uri, group):
    return Song(uri, "T" + uri, "A", None, group, [], "track", False)


# Old tests were written in song groups; each maps to the face state whose first pick
# lands in that group (Stressed lifts from Chill; Sad matches Melancholy in Match mode).
_STATE_FOR = {MoodGroup.UPBEAT: FaceState.HAPPY, MoodGroup.MELANCHOLY: FaceState.SAD,
              MoodGroup.FOCUS: FaceState.FOCUSED, MoodGroup.CHILL: FaceState.STRESSED,
              MoodGroup.INTENSE: FaceState.EXCITED}


def mood(state, t=0.0, v=0.0, a=0.0):
    state = _STATE_FOR.get(state, state)
    return FaceMood(state, t, "", v, a, {}, None)


def pb(uri, progress=0, duration=200000, playing=True):
    return PlaybackInfo(uri, progress, duration, playing, "dev")


SONGS = [mk("c1", MoodGroup.CHILL), mk("c2", MoodGroup.CHILL), mk("u1", MoodGroup.UPBEAT),
         mk("u2", MoodGroup.UPBEAT), mk("m1", MoodGroup.MELANCHOLY), mk("f1", MoodGroup.FOCUS)]


def make(tmp_path, switch_mode="wait", mode="match", songs=SONGS, away=10, force=None, seed=2,
         hour_fn=lambda: 14):
    lib = SongLibrary(tmp_path / "l.db")
    for s in songs:
        lib.upsert(s)
    svc = FakeService()
    clock = Clock()
    settings = Settings(switch_mode=switch_mode, mode=mode, away_pause_minutes=away)
    sel = SongSelector(lib, random.Random(1))
    eng = Engine(svc, sel, settings, clock, random.Random(seed), force, hour_fn=hour_fn)
    return eng, svc, clock


def started(tmp_path, group=MoodGroup.CHILL, **kw):
    """Engine with an initial song playing for `group`."""
    eng, svc, clock = make(tmp_path, **kw)
    eng.on_mood(mood(group))
    eng.tick()
    uri = svc.names("play")[-1][0]
    svc.pb = pb(uri)
    eng.tick()
    return eng, svc, clock, uri


def test_initial_start_plays_even_in_wait_mode(tmp_path):
    eng, svc, _ = make(tmp_path, switch_mode="wait")
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert len(svc.names("play")) == 1 and not svc.names("queue")
    assert eng.current_pick.group == MoodGroup.CHILL
    assert eng.status.kind == "ok"


def test_wait_mode_queues_not_plays(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL, switch_mode="wait")
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    assert len(svc.names("play")) == 1
    q = svc.names("queue")
    assert len(q) == 1 and q[0][0] in ("u1", "u2")
    eng.tick()
    assert len(svc.names("queue")) == 1
    # song ends: queued becomes current
    svc.pb = pb(q[0][0])
    eng.tick()
    assert eng.current_pick.song.uri == q[0][0]
    assert len(svc.names("queue")) == 1 and len(svc.names("play")) == 1


def test_immediate_mode_plays(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL, switch_mode="immediate")
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    assert len(svc.names("play")) == 2
    assert svc.names("play")[-1][0] in ("u1", "u2")
    assert not svc.names("queue")
    assert eng.current_pick.group == MoodGroup.UPBEAT


def test_near_end_queues_next_from_current_target(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    svc.pb = pb(uri, progress=198000)
    eng.tick()
    eng.tick()
    q = svc.names("queue")
    assert len(q) == 1 and q[0][0] in ("c1", "c2")


def test_lift_mode_steps_one_group_per_song(tmp_path):
    eng, svc, _ = make(tmp_path, switch_mode="wait", mode="lift")
    eng.on_mood(mood(MoodGroup.MELANCHOLY))
    eng.tick()
    first = svc.names("play")[0][0]
    assert eng.current_pick.group == MoodGroup.CHILL
    svc.pb = pb(first, progress=199000)
    eng.tick()
    q = svc.names("queue")
    assert len(q) == 1 and q[0][0] in ("c1", "c2")  # still MELANCHOLY mood -> CHILL again
    svc.pb = pb(q[0][0])
    eng.tick()
    eng.on_mood(mood(MoodGroup.CHILL))
    svc.pb = pb(q[0][0], progress=199000)
    eng.tick()
    nxt = svc.names("queue")[-1][0]
    assert nxt not in (first, q[0][0])  # both Chill songs just played: no repeat


def test_manual_song_backs_off(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    svc.pb = pb("spotify:manual", progress=199000)
    eng.tick()
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    assert not svc.names("queue") and len(svc.names("play")) == 1
    # manual song ends -> we take over from the current target
    svc.pb = pb("autoplay:x")
    eng.tick()
    assert len(svc.names("play")) == 2
    assert svc.names("play")[-1][0] in ("u1", "u2")


def test_poor_quality_freezes_music(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL, switch_mode="immediate")
    eng.on_quality(QualityReport(False, "Too dark"))
    assert eng.status.kind == "warning" and eng.status.message == "Too dark"
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    assert len(svc.names("play")) == 1 and not svc.names("queue")
    eng.on_quality(QualityReport(True))
    assert eng.status.kind == "ok"


def test_away_pauses_then_resumes(tmp_path):
    eng, svc, clock, uri = started(tmp_path, MoodGroup.CHILL, away=10)
    eng.on_face_present(False)
    clock.t += 599
    eng.tick()
    assert not svc.names("pause")
    clock.t += 2
    eng.tick()
    eng.tick()
    assert len(svc.names("pause")) == 1
    eng.on_face_present(True)
    assert len(svc.names("resume")) == 1


def test_away_does_not_resume_if_not_paused_by_us(tmp_path):
    eng, svc, clock, uri = started(tmp_path, MoodGroup.CHILL, away=0)
    eng.on_face_present(False)
    clock.t += 5000
    eng.tick()
    eng.on_face_present(True)
    assert not svc.names("pause") and not svc.names("resume")


def test_no_active_device_status_and_no_crash(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert eng.status.kind == "error" and eng.status.message == "Open Spotify on any device"
    eng.tick()  # retries, succeeds, recovers
    assert eng.status.kind == "ok"
    assert eng.current_pick is not None


def test_unavailable_retries_next_tick(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.fail["play"] = [SpotifyUnavailable("x")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert eng.status.kind == "warning"
    assert eng.status.message == "Can't reach Spotify. Retrying…"
    eng.tick()
    assert len(svc.names("play")) == 2 and eng.status.kind == "ok"


@pytest.mark.parametrize("exc,kind,msg", [
    (NotPremium("x"), "error", "Spotify Premium is needed for playback control"),
    (AuthRequired("x"), "error", "Spotify login expired. Please log in again"),
    (SpotifyError("boom"), "error", "Spotify error: boom"),
])
def test_error_messages(tmp_path, exc, kind, msg):
    eng, svc, _ = make(tmp_path)
    svc.fail["play"] = [exc]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert (eng.status.kind, eng.status.message) == (kind, msg)


def test_unexpected_exception_is_contained(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.fail["play"] = [RuntimeError("bug")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert eng.status.kind == "error"
    assert eng.status.message == "Something went wrong. Retrying…"
    eng.tick()
    assert eng.status.kind == "ok"


def test_no_sorted_songs_warning(tmp_path):
    eng, svc, _ = make(tmp_path, songs=[mk("x", MoodGroup.UNSORTED)])
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert eng.status.kind == "warning"
    assert eng.status.message == "No songs sorted yet. Scanning your playlist…"
    assert not svc.names("play")


def test_wrong_vibe_moves_song_and_skips_if_mismatch(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    eng.wrong_vibe(MoodGroup.CHILL)  # same group as target: no skip
    assert len(svc.names("play")) == 1
    eng.wrong_vibe(MoodGroup.MELANCHOLY)
    assert eng.selector.library.get(uri).group == MoodGroup.MELANCHOLY
    assert len(svc.names("play")) == 2
    assert svc.names("play")[-1][0] != uri


def test_not_how_i_feel_calls_force(tmp_path):
    got = []
    eng, svc, _ = make(tmp_path, force=got.append)
    eng.not_how_i_feel(MoodGroup.UPBEAT)
    assert got == [MoodGroup.UPBEAT]


def test_skip_previous_toggle(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    eng.skip()
    assert len(svc.names("play")) == 2
    eng.previous()
    assert svc.names("previous")
    svc.pb = pb("c1", playing=True)
    eng.toggle_pause()
    assert svc.names("pause")
    svc.pb = pb("c1", playing=False)
    eng.toggle_pause()
    assert svc.names("resume")


def test_disabled_does_nothing(tmp_path):
    eng, svc, _ = make(tmp_path)
    eng.set_enabled(False)
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert not svc.calls
    eng.set_enabled(True)
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert svc.names("play")


def test_history_trimmed_to_60_minutes(tmp_path):
    eng, svc, clock = make(tmp_path)
    eng.on_mood(mood(MoodGroup.CHILL, v=0.1, a=0.2))
    t0 = clock.t
    clock.t += 3601
    eng.on_mood(mood(MoodGroup.CHILL, v=0.3, a=0.4))
    assert eng.history == [(clock.t, 0.3, 0.4)]
    assert t0 not in [h[0] for h in eng.history]


def test_listeners_called_and_failures_contained(tmp_path):
    eng, svc, _ = make(tmp_path)
    seen = []

    def bad():
        raise RuntimeError("listener")

    eng.listeners.extend([bad, lambda: seen.append(1)])
    eng.on_mood(mood(MoodGroup.CHILL))
    assert seen


def test_stressed_lift_starts_at_chill_every_time(tmp_path):
    # The old random Chill->Upbeat jump is gone: lifts climb one step per song instead.
    for seed in range(10):
        (tmp_path / f"s{seed}").mkdir()
        eng, svc, _ = make(tmp_path / f"s{seed}", mode="lift", seed=seed)
        eng.on_mood(mood(FaceState.STRESSED))
        eng.tick()
        assert eng.current_pick.group == MoodGroup.CHILL


def test_second_manual_pick_is_not_overridden(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    svc.pb = pb("A", progress=10000)
    eng.tick()
    svc.pb = pb("B", progress=5000)  # user switched mid-song
    eng.tick()
    eng.tick()
    assert len(svc.names("play")) == 1
    svc.pb = pb("B", progress=199000)
    eng.tick()
    svc.pb = pb("autoplay", progress=0)
    eng.tick()
    assert len(svc.names("play")) == 2


def test_stopped_after_song_end_restarts(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    svc.pb = pb(uri, progress=100000, playing=False)  # user paused mid-song
    eng.tick()
    assert len(svc.names("play")) == 1
    svc.pb = pb(uri, progress=199500, playing=False)
    eng.tick()
    assert len(svc.names("play")) == 2


def test_stopped_reset_progress_restarts(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    svc.pb = pb(uri, progress=198000)
    eng.tick()
    svc.fail["queue"] = [SpotifyUnavailable("x")]
    svc.pb = pb(uri, progress=0, playing=False)
    eng.tick()
    assert len(svc.names("play")) == 2


def test_manual_song_end_then_stopped_clears_backoff(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    svc.pb = pb("A", progress=199000)
    eng.tick()
    svc.pb = pb("A", progress=199800, playing=False)
    eng.tick()
    assert len(svc.names("play")) == 2


def test_spotify_closed_retries_and_recovers(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    svc.pb = None
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.tick()
    assert eng.status.message == "Open Spotify on any device"
    eng.tick()
    assert eng.status.kind == "ok" and len(svc.names("play")) == 3
    for _ in range(3):  # playback still empty within the settle grace: no churn
        eng.tick()
    assert len(svc.names("play")) == 3
    eng.tick()  # grace expired: retry happens
    assert len(svc.names("play")) == 4


def test_single_device_fallback(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.devs = [Device("d1", "PC", "Computer", False)]
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert svc.names("play")[-1][1] == "d1" and eng.status.kind == "ok"
    assert eng.current_pick is not None


def test_multiple_devices_choose_then_set_device(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.devs = [Device("d1", "PC", "Computer", False), Device("d2", "Phone", "Phone", False)]
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert eng.status.message == "Choose a Spotify device"
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.tick()  # status must stay while waiting for a choice
    assert eng.status.message == "Choose a Spotify device"
    assert [d.id for d in eng.available_devices()] == ["d1", "d2"]
    eng.set_device("d2")
    assert svc.names("play")[-1][1] == "d2" and eng.current_pick is not None
    assert eng.status.kind == "ok"


def test_zero_devices_keeps_open_spotify(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert eng.status.message == "Open Spotify on any device"


def test_failed_resume_is_retried(tmp_path):
    eng, svc, clock, uri = started(tmp_path, MoodGroup.CHILL, away=10)
    eng.on_face_present(False)
    clock.t += 700
    eng.tick()
    assert len(svc.names("pause")) == 1
    svc.pb = pb(uri, progress=50000, playing=False)
    svc.fail["resume"] = [SpotifyUnavailable("x")]
    eng.on_face_present(True)
    eng.tick()
    assert len(svc.names("resume")) == 2
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    assert len(svc.names("queue")) == 1  # engine is live again


def test_manual_resume_clears_paused_flag(tmp_path):
    eng, svc, clock, uri = started(tmp_path, MoodGroup.CHILL, away=10)
    eng.on_face_present(False)
    clock.t += 700
    eng.tick()
    svc.fail["resume"] = [SpotifyUnavailable("x")]
    eng.on_face_present(True)
    svc.pb = pb(uri, playing=True)
    eng.tick()
    assert len(svc.names("resume")) == 1
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    assert len(svc.names("queue")) == 1


def test_orphaned_queue_is_still_ours(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL)
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    queued = svc.names("queue")[0][0]
    eng.skip()
    played = svc.names("play")[-1][0]
    svc.pb = pb(played)
    eng.tick()
    svc.pb = pb(queued)  # Spotify plays the orphaned queue entry
    eng.tick()
    assert eng.current_pick.song.uri == queued
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert len(svc.names("play")) == 2  # no back-off took place


# ---- C1: no Spotify I/O per camera frame -----------------------------------
@pytest.mark.parametrize("scenario", ["first_scan", "spotify_closed", "empty_library"])
def test_on_mood_never_calls_spotify_and_tick_is_bounded(tmp_path, scenario):
    songs = [] if scenario == "empty_library" else SONGS
    eng, svc, clock = make(tmp_path, songs=songs)
    if scenario == "spotify_closed":
        svc.fail["play"] = [NoActiveDevice("x") for _ in range(200)]
    for _ in range(80):  # 10 s of frames at 8 fps
        clock.t += 0.125
        eng.on_mood(mood(MoodGroup.CHILL))
    assert svc.calls == []
    eng.tick()
    assert len([c for c in svc.calls if c[0] != "devices"]) <= 3
    assert len(svc.names("devices")) <= 1


def test_history_downsampled_to_one_point_per_5s(tmp_path):
    eng, svc, clock = make(tmp_path)
    for _ in range(80):
        clock.t += 0.125
        eng.on_mood(mood(MoodGroup.CHILL))
    assert 2 <= len(eng.history) <= 3
    times = [h[0] for h in eng.history]
    assert all(b - a >= 5 for a, b in zip(times, times[1:]))


def test_rate_limited_backs_off_without_sleeping(tmp_path):
    from moodmusic.spotify.client import RateLimited
    eng, svc, clock = make(tmp_path)
    eng.on_mood(mood(MoodGroup.CHILL))
    svc.fail["playback"] = [RateLimited("slow", retry_after=30)]
    eng.tick()
    assert (eng.status.kind, eng.status.message) == (
        "warning", "Spotify asked us to slow down. Retrying…")
    n = len(svc.calls)
    clock.t += 29
    eng.tick()
    eng.skip()
    eng.toggle_pause()
    assert len(svc.calls) == n  # nothing reaches Spotify until the deadline
    clock.t += 2
    eng.tick()
    assert len(svc.calls) > n and eng.status.kind == "ok"


def test_rate_limit_deadline_is_capped(tmp_path):
    from moodmusic.spotify.client import RateLimited
    eng, svc, clock = make(tmp_path)
    svc.fail["playback"] = [RateLimited("slow", retry_after=999)]
    eng.tick()
    n = len(svc.calls)
    clock.t += 61
    eng.tick()
    assert len(svc.calls) > n


def test_set_service_swaps_service_and_clears_auth_error(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.fail["playback"] = [AuthRequired("x")]
    eng.tick()
    assert eng.status.message == "Spotify login expired. Please log in again"
    new = FakeService()
    eng.set_service(new)
    assert eng.service is new and eng.status.message != "Spotify login expired. Please log in again"
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert new.names("play") and len(svc.names("playback")) == 1


# ---- I1: respect a pause made by the user ----------------------------------
def test_app_pause_is_not_undone_by_immediate_mood_change(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL, switch_mode="immediate")
    svc.pb = pb(uri, progress=50000)
    eng.toggle_pause()
    assert svc.names("pause")
    svc.pb = pb(uri, progress=50000, playing=False)
    eng.on_mood(mood(MoodGroup.UPBEAT))
    for _ in range(4):
        eng.tick()
    assert len(svc.names("play")) == 1 and not svc.names("queue")
    eng.toggle_pause()  # user resumes: mood-driven switching is live again
    assert svc.names("resume")
    svc.pb = pb(uri, progress=52000)
    eng.tick()
    eng.tick()
    assert len(svc.names("play")) == 2


def test_spotify_pause_is_respected_until_resumed(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL, switch_mode="immediate")
    svc.pb = pb(uri, progress=50000, playing=False)  # paused in Spotify
    eng.tick()
    eng.on_mood(mood(MoodGroup.UPBEAT))
    eng.tick()
    svc.pb = None  # Spotify closed while paused: no R11 restart either
    for _ in range(5):
        eng.tick()
    assert len(svc.names("play")) == 1
    svc.pb = pb(uri, progress=50000, playing=True)  # resumed in Spotify
    eng.tick()
    assert len(svc.names("play")) == 2


def test_skip_and_wrong_vibe_still_act_while_paused(tmp_path):
    eng, svc, _, uri = started(tmp_path, MoodGroup.CHILL, switch_mode="immediate")
    svc.pb = pb(uri, progress=50000, playing=False)
    eng.tick()
    eng.skip()
    assert len(svc.names("play")) == 2
    svc.pb = pb(svc.names("play")[-1][0], progress=1000, playing=False)
    eng.tick()
    eng.tick()
    eng.wrong_vibe(MoodGroup.MELANCHOLY)
    assert len(svc.names("play")) == 3


# ---- I2: don't pull playback back to a remembered device -------------------
def test_chosen_device_dropped_once_playback_is_active(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.devs = [Device("d1", "PC", "Computer", False), Device("d2", "Phone", "Phone", False)]
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    eng.set_device("d2")
    assert svc.names("play")[-1][1] == "d2"
    svc.pb = PlaybackInfo(svc.names("play")[-1][0], 1000, 200000, True, "speaker")  # user moved
    eng.tick()
    eng.skip()
    assert svc.names("play")[-1][1] is None


def test_single_device_fallback_not_reused_after_active(tmp_path):
    eng, svc, _ = make(tmp_path)
    svc.devs = [Device("d1", "PC", "Computer", False)]
    svc.fail["play"] = [NoActiveDevice("x")]
    eng.on_mood(mood(MoodGroup.CHILL))
    eng.tick()
    assert svc.names("play")[-1][1] == "d1"
    svc.pb = PlaybackInfo(svc.names("play")[-1][0], 1000, 200000, True, "d1")
    eng.tick()
    eng.skip()
    assert svc.names("play")[-1][1] is None


# ---- face states -> music intent ------------------------------------------------
STATE_SONGS = [mk("f1", MoodGroup.FOCUS), mk("p1", MoodGroup.PROFOUND),
               mk("r1", MoodGroup.ROMANTIC), mk("r2", MoodGroup.ROMANTIC),
               mk("c1", MoodGroup.CHILL), mk("c2", MoodGroup.CHILL),
               mk("u1", MoodGroup.UPBEAT), mk("u2", MoodGroup.UPBEAT),
               mk("y1", MoodGroup.PARTY), mk("y2", MoodGroup.PARTY)]
GROUP_OF = {s.uri: s.group for s in STATE_SONGS}


def _end_song(eng, svc):
    """Finish the current song (Spotify stops at its end) and let the engine pick the next."""
    uri = svc.names("play")[-1][0]
    svc.pb = pb(uri, progress=199000, duration=200000)
    eng.tick()
    svc.pb = pb(uri, progress=200000, duration=200000, playing=False)
    eng.tick()
    return svc.names("play")[-1][0]


def test_focused_state_plays_focus_group(tmp_path):
    eng, svc, _ = make(tmp_path, songs=STATE_SONGS)
    eng.on_mood(mood(FaceState.FOCUSED))
    eng.tick()
    assert GROUP_OF[svc.names("play")[-1][0]] == MoodGroup.FOCUS


def test_deep_thought_plays_profound(tmp_path):
    eng, svc, _ = make(tmp_path, songs=STATE_SONGS)
    eng.on_mood(mood(FaceState.DEEP_THOUGHT))
    eng.tick()
    assert GROUP_OF[svc.names("play")[-1][0]] == MoodGroup.PROFOUND


def test_tired_lift_advances_one_step_per_song_and_resets_on_state_change(tmp_path):
    eng, svc, _ = make(tmp_path, songs=STATE_SONGS)  # Match mode: Tired still lifts
    eng.on_mood(mood(FaceState.TIRED))
    eng.tick()
    first = svc.names("play")[-1][0]
    assert GROUP_OF[first] in (MoodGroup.ROMANTIC, MoodGroup.CHILL)
    second = _end_song(eng, svc)
    assert GROUP_OF[second] in (MoodGroup.CHILL, MoodGroup.UPBEAT)
    third = _end_song(eng, svc)
    assert GROUP_OF[third] == MoodGroup.UPBEAT
    eng.on_mood(mood(FaceState.STRESSED, t=5))  # new state: lift restarts at its first step
    eng.on_mood(mood(FaceState.TIRED, t=6))
    fourth = _end_song(eng, svc)
    assert GROUP_OF[fourth] in (MoodGroup.ROMANTIC, MoodGroup.CHILL)


def test_bored_requests_fresh(tmp_path):
    eng, svc, _ = make(tmp_path, songs=STATE_SONGS)
    eng.selector.library.record_play("u1", 1.0)
    eng.selector.library.record_play("y1", 2.0)
    eng.on_mood(mood(FaceState.BORED))
    eng.tick()
    uri = svc.names("play")[-1][0]
    assert uri in ("u2", "y2")  # never-played energetic songs first
    assert "haven't heard in a while" in eng.current_pick.reason


def test_sleepy_night_decided_at_selection_not_midsong(tmp_path):
    hour = [20]
    eng, svc, _ = make(tmp_path, songs=STATE_SONGS, switch_mode="immediate",
                       hour_fn=lambda: hour[0])
    eng.on_mood(mood(FaceState.SLEEPY))
    eng.tick()
    first = svc.names("play")[-1][0]
    assert GROUP_OF[first] == MoodGroup.UPBEAT  # 20:00 is day: waking you up
    svc.pb = pb(first, progress=60000)
    hour[0] = 21
    eng.tick()
    eng.tick()
    assert svc.names("play")[-1][0] == first and svc.names("queue") == []  # no mid-song switch
    nxt = _end_song(eng, svc)
    assert GROUP_OF[nxt] in (MoodGroup.CHILL, MoodGroup.PROFOUND)  # night: winding down
    assert "winding down" in eng.current_pick.reason


def test_reason_includes_intent_note(tmp_path):
    eng, svc, _ = make(tmp_path, songs=STATE_SONGS)
    eng.on_mood(mood(FaceState.STRESSED))
    eng.tick()
    assert eng.current_pick.reason.endswith(" — lifting you up")


def test_not_how_i_feel_forwards_face_state(tmp_path):
    got = []
    eng, _, _ = make(tmp_path, force=got.append)
    eng.not_how_i_feel(FaceState.LOVE)
    assert got == [FaceState.LOVE]


def test_play_history_uses_wall_clock(tmp_path):
    lib = SongLibrary(tmp_path / "w.db")
    for s in SONGS:
        lib.upsert(s)
    svc = FakeService()
    eng = Engine(svc, SongSelector(lib, random.Random(1)), Settings(), Clock(),
                 random.Random(2), hour_fn=lambda: 14, wall_clock=lambda: 1_790_000_000.0)
    eng.on_mood(mood(FaceState.HAPPY))
    eng.tick()
    uri = svc.names("play")[-1][0]
    assert lib.last_played()[uri] == 1_790_000_000.0  # survives reboots (not monotonic)


def test_is_playing_follows_playback_and_pause(tmp_path):
    eng, svc, clock, _ = started(tmp_path)
    assert eng.is_playing is True
    eng.toggle_pause()
    assert eng.is_playing is False
    svc.pb = None
    eng.tick()
    assert eng.is_playing is False
