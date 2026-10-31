import random

from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.states import FaceState
from moodmusic.mood.tracker import FaceMood
from moodmusic.music.library import Song, SongLibrary
from moodmusic.music.selector import SongSelector


def mk(uri, group, tags=("a", "b"), source="track"):
    return Song(uri, "T" + uri, "A", None, group, list(tags), source, False)


def state(face=FaceState.STRESSED):
    return FaceMood(face)


def sel(tmp_path, songs):
    lib = SongLibrary(tmp_path / "l.db")
    for s in songs:
        lib.upsert(s)
    return SongSelector(lib, random.Random(1))


def test_no_repeat_until_most_played(tmp_path):
    s = sel(tmp_path, [mk(f"u{i}", MoodGroup.CHILL) for i in range(10)])
    seen = []
    for _ in range(8):
        p = s.pick([MoodGroup.CHILL], state())
        seen.append(p.song.uri)
        s.mark_played(p.song.uri)
    assert len(set(seen)) == 8


def test_all_recent_still_picks(tmp_path):
    s = sel(tmp_path, [mk("u0", MoodGroup.CHILL)])
    for _ in range(3):
        p = s.pick([MoodGroup.CHILL], state())
        s.mark_played(p.song.uri)
        assert p.song.uri == "u0"


def test_empty_group_falls_back(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.UPBEAT), mk("u2", MoodGroup.UPBEAT)])
    p = s.pick([MoodGroup.INTENSE], state())
    assert p.group == MoodGroup.UPBEAT
    assert p.fell_back_from == MoodGroup.INTENSE
    assert "no Intense songs" in p.reason


def test_unsorted_never_picked(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.UNSORTED)])
    assert s.pick([MoodGroup.CHILL], state()) is None
    s2 = sel(tmp_path / "x", [mk("u1", MoodGroup.UNSORTED), mk("u2", MoodGroup.FOCUS)])
    for _ in range(10):
        assert s2.pick([MoodGroup.CHILL], state()).song.uri == "u2"


def test_reason_text(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.CHILL, tags=("mellow", "acoustic", "x"))])
    p = s.pick([MoodGroup.CHILL], state(FaceState.STRESSED))
    assert p.reason == "Chill: you seem stressed; tagged mellow, acoustic"
    assert p.fell_back_from is None


def test_reason_artist_and_user(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.CHILL, source="artist")])
    assert s.pick([MoodGroup.CHILL], state()).reason.endswith("; sorted by artist style")
    s = sel(tmp_path / "y", [mk("u1", MoodGroup.CHILL, source="user")])
    assert s.pick([MoodGroup.CHILL], state(FaceState.SAD)).reason == \
        "Chill: you seem sad; you filed it here"


class FaceMoodStub:
    def __init__(self, label):
        self.state = type("S", (), {"label": label})()


def test_empty_focus_falls_back_to_chill(tmp_path):
    s = sel(tmp_path, [mk("c1", MoodGroup.CHILL), mk("u1", MoodGroup.UPBEAT)])
    p = s.pick([MoodGroup.FOCUS], FaceMoodStub("Focused"))
    assert p.group == MoodGroup.CHILL
    assert p.fell_back_from == MoodGroup.FOCUS
    assert "no Focus songs yet" in p.reason
    assert p.reason.startswith("Chill: you seem focused")


def test_pick_groups_order(tmp_path):
    s = sel(tmp_path, [mk("c1", MoodGroup.CHILL), mk("u1", MoodGroup.UPBEAT)])
    p = s.pick([MoodGroup.ROMANTIC, MoodGroup.CHILL], FaceMoodStub("Tired"))
    assert p.group == MoodGroup.CHILL and p.fell_back_from is None
    assert p.groups == [MoodGroup.ROMANTIC, MoodGroup.CHILL]


def test_fresh_prefers_never_played(tmp_path):
    songs = [mk(f"u{i}", MoodGroup.UPBEAT if i % 2 else MoodGroup.PARTY) for i in range(8)]
    s = sel(tmp_path, songs)
    for i in range(6):
        s.library.record_play(f"u{i}", 1000.0 + i)
    for _ in range(20):
        p = s.pick([MoodGroup.UPBEAT, MoodGroup.PARTY], FaceMoodStub("Bored"), fresh=True, now=2000.0)
        assert p.song.uri in {"u6", "u7"}
        assert "haven't heard in a while" in p.reason


def test_mark_played_records_history(tmp_path):
    s = sel(tmp_path, [mk("u1", MoodGroup.CHILL)])
    s.mark_played("u1", 1234.5)
    assert s.library.last_played() == {"u1": 1234.5}
