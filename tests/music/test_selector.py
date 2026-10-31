import random

from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.smoother import MoodState
from moodmusic.music.library import Song, SongLibrary
from moodmusic.music.selector import SongSelector


def mk(uri, group, tags=("a", "b"), source="track"):
    return Song(uri, "T" + uri, "A", None, group, list(tags), source, False)


def state(group=MoodGroup.CHILL):
    return MoodState(group, 0.0, 0.0, 0.0, {}, None)


def sel(tmp_path, songs):
    lib = SongLibrary(tmp_path / "l.db")
    for s in songs:
        lib.upsert(s)
    return SongSelector(lib, random.Random(1))


def test_no_repeat_until_most_played(tmp_path):
    s = sel(tmp_path, [mk(f"u{i}", MoodGroup.CHILL) for i in range(10)])
    seen = []
    for _ in range(8):
        p = s.pick(MoodGroup.CHILL, state())
        seen.append(p.song.uri)
        s.mark_played(p.song.uri)
    assert len(set(seen)) == 8


def test_all_recent_still_picks(tmp_path):
    s = sel(tmp_path, [mk("u0", MoodGroup.CHILL)])
    for _ in range(3):
        p = s.pick(MoodGroup.CHILL, state())
        s.mark_played(p.song.uri)
        assert p.song.uri == "u0"


def test_empty_group_falls_back(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.UPBEAT), mk("u2", MoodGroup.UPBEAT)])
    p = s.pick(MoodGroup.INTENSE, state())
    assert p.group == MoodGroup.UPBEAT
    assert p.fell_back_from == MoodGroup.INTENSE
    assert "no Intense songs" in p.reason


def test_unsorted_never_picked(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.UNSORTED)])
    assert s.pick(MoodGroup.CHILL, state()) is None
    s2 = sel(tmp_path / "x", [mk("u1", MoodGroup.UNSORTED), mk("u2", MoodGroup.FOCUS)])
    for _ in range(10):
        assert s2.pick(MoodGroup.CHILL, state()).song.uri == "u2"


def test_reason_text(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.CHILL, tags=("mellow", "acoustic", "x"))])
    p = s.pick(MoodGroup.CHILL, state(MoodGroup.CHILL))
    assert p.reason == "Chill: you look calm and positive; tagged mellow, acoustic"
    assert p.fell_back_from is None


def test_reason_artist_and_user(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.CHILL, source="artist")])
    assert s.pick(MoodGroup.CHILL, state()).reason.endswith("; sorted by artist style")
    s = sel(tmp_path / "y", [mk("u1", MoodGroup.CHILL, source="user")])
    assert s.pick(MoodGroup.CHILL, state(MoodGroup.MELANCHOLY)).reason == \
        "Chill: you look low; you filed it here"
