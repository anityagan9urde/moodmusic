import pytest

from moodmusic.mood.groups import MoodGroup
from moodmusic.music.lastfm import LastFmError
from moodmusic.music.library import Song, SongLibrary
from moodmusic.music.scanner import Scanner, suggest_group
from moodmusic.spotify.client import SpotifyError

SAD = [("sad", 100)]
HAPPY = [("happy", 100)]


class FakeService:
    def __init__(self, tracks, error=None):
        self.tracks, self.error = tracks, error

    def iter_source_tracks(self, playlist_id):
        if self.error:
            raise self.error
        return iter(self.tracks)


class FakeLastFm:
    def __init__(self, track=None, artist=None, fail=()):
        self.track, self.artist, self.fail = track or {}, artist or {}, set(fail)
        self.track_calls, self.artist_calls = [], []

    def track_tags(self, artist, title):
        self.track_calls.append((artist, title))
        if title in self.fail:
            raise LastFmError("down")
        return self.track.get(title, [])

    def artist_tags(self, artist):
        self.artist_calls.append(artist)
        return self.artist.get(artist, [])


def t(n, artist="Art"):
    return (f"u{n}", f"T{n}", artist, None)


def song(uri, artist="Art", group=MoodGroup.CHILL):
    return Song(uri, "T" + uri, artist, None, group, [], "track", False)


@pytest.fixture
def lib(tmp_path):
    return SongLibrary(tmp_path / "l.db")


def run(svc, fm, lib, stop=lambda: False):
    events = []
    res = Scanner(svc, fm, lib).run(None, events.append, stop)
    return res, events


def test_scans_only_new(lib):
    lib.upsert(song("u1"))
    lib.upsert(song("u2"))
    fm = FakeLastFm(track={"T3": SAD})
    res, _ = run(FakeService([t(1), t(2), t(3)]), fm, lib)
    assert len(fm.track_calls) == 1
    assert lib.get("u3").group == MoodGroup.MELANCHOLY
    assert lib.get("u3").source == "track"
    assert lib.get("u3").tags == ["sad"]
    assert res.total == 1 and res.done == 1


def test_removes_missing(lib):
    lib.upsert(song("u1"))
    lib.upsert(song("gone"))
    run(FakeService([t(1)]), FakeLastFm(), lib)
    assert lib.uris() == {"u1"}


def test_artist_fallback_sets_source_artist(lib):
    fm = FakeLastFm(artist={"Art": HAPPY})
    run(FakeService([t(1, "Art, Other")]), fm, lib)
    s = lib.get("u1")
    assert s.group == MoodGroup.UPBEAT and s.source == "artist"
    assert fm.track_calls == [("Art", "T1")]


def test_artist_cache_per_run(lib):
    fm = FakeLastFm(artist={"Art": HAPPY})
    run(FakeService([t(1, "Art"), t(2, "ART")]), fm, lib)
    assert len(fm.artist_calls) == 1


def test_unsorted_when_no_tags(lib):
    run(FakeService([t(1)]), FakeLastFm(), lib)
    s = lib.get("u1")
    assert s.group == MoodGroup.UNSORTED and s.source == "none" and s.tags == []


def test_lastfm_error_skips_song_and_continues(lib):
    fm = FakeLastFm(track={"T2": SAD}, fail={"T1"})
    res, _ = run(FakeService([t(1), t(2)]), fm, lib)
    assert lib.get("u1") is None
    assert lib.get("u2") is not None
    assert res.error is None


def test_five_consecutive_errors_stop_run(lib):
    fm = FakeLastFm(fail={f"T{i}" for i in range(1, 9)})
    res, _ = run(FakeService([t(i) for i in range(1, 9)]), fm, lib)
    assert len(fm.track_calls) == 5
    assert res.error == "Can't reach Last.fm right now. Will retry next time."
    assert lib.uris() == set()


def test_error_streak_resets_on_success(lib):
    fail = {"T1", "T2", "T3", "T4", "T6", "T7", "T8", "T9"}
    fm = FakeLastFm(track={"T5": SAD}, fail=fail)
    res, _ = run(FakeService([t(i) for i in range(1, 10)]), fm, lib)
    assert res.error is None
    assert len(fm.track_calls) == 9


def test_stop_flag_halts(lib):
    n = {"c": 0}

    def stop():
        n["c"] += 1
        return n["c"] > 1

    fm = FakeLastFm()
    res, _ = run(FakeService([t(1), t(2), t(3)]), fm, lib, stop)
    assert len(fm.track_calls) == 1
    assert res.done == 1 and res.total == 3


def test_progress_callback_called_per_song(lib):
    _, events = run(FakeService([t(1), t(2)]), FakeLastFm(), lib)
    assert [(e.done, e.total) for e in events] == [(1, 2), (2, 2)]
    assert events[0].current == "Art – T1"


def test_spotify_error_propagates(lib):
    with pytest.raises(SpotifyError):
        run(FakeService([], error=SpotifyError("x")), FakeLastFm(), lib)


def test_suggest_group_by_artist(lib):
    lib.upsert(song("a", group=MoodGroup.CHILL))
    lib.upsert(song("b", group=MoodGroup.CHILL))
    lib.upsert(song("c", group=MoodGroup.UPBEAT))
    lib.upsert(song("d", group=MoodGroup.UNSORTED))
    lib.upsert(song("o", artist="Other", group=MoodGroup.INTENSE))
    target = song("d", group=MoodGroup.UNSORTED)
    assert suggest_group(target, lib) == MoodGroup.CHILL
    assert suggest_group(song("z", artist="Nobody"), lib) is None


def test_suggest_group_tie_uses_declaration_order(lib):
    lib.upsert(song("a", group=MoodGroup.INTENSE))
    lib.upsert(song("b", group=MoodGroup.UPBEAT))
    assert suggest_group(song("n", group=MoodGroup.UNSORTED), lib) == MoodGroup.UPBEAT


def test_suggest_group_excludes_self(lib):
    lib.upsert(song("a", group=MoodGroup.CHILL))
    assert suggest_group(song("a", group=MoodGroup.CHILL), lib) is None


def test_suggest_groups_matches_suggest_group(lib):
    from moodmusic.music.scanner import suggest_groups
    songs = [
        song("a1", artist="Alpha", group=MoodGroup.CHILL),
        song("a2", artist="alpha, Beta", group=MoodGroup.CHILL),
        song("a3", artist="Alpha", group=MoodGroup.UPBEAT),
        song("a4", artist="Alpha", group=MoodGroup.UNSORTED),
        song("b1", artist="Beta", group=MoodGroup.UPBEAT),
        song("b2", artist="Beta", group=MoodGroup.FOCUS),
        song("b3", artist="Beta, Alpha", group=MoodGroup.UNSORTED),
        song("c1", artist="Gamma", group=MoodGroup.UNSORTED),
        song("c2", artist="Gamma", group=MoodGroup.UNSORTED),
    ]
    for s in songs:
        lib.upsert(s)
    all_songs = lib.songs()
    got = suggest_groups(all_songs)
    want = {s.uri: suggest_group(s, lib) for s in all_songs if s.group == MoodGroup.UNSORTED}
    assert got == want
    assert got["a4"] == MoodGroup.CHILL and got["c1"] is None
