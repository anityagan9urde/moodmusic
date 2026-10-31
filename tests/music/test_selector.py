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


HOUR = 3600.0


def test_cooldown_survives_restart(tmp_path):
    # a new selector (app restart) on the same library still skips songs played recently
    s = sel(tmp_path, [mk(f"u{i}", MoodGroup.CHILL) for i in range(3)])
    for uri in ("u0", "u1"):
        s.library.record_play(uri, 10 * HOUR)
    fresh = SongSelector(s.library, random.Random(1))
    for _ in range(5):
        assert fresh.pick([MoodGroup.CHILL], state(), now=11 * HOUR).song.uri == "u2"


def test_song_returns_after_cooldown(tmp_path):
    s = sel(tmp_path, [mk("u0", MoodGroup.CHILL)])
    s.library.record_play("u0", 0.0)
    s.cooldown_s = lambda: 3 * HOUR
    p = s.pick([MoodGroup.CHILL], state(), now=3 * HOUR + 1)
    assert p.song.uri == "u0" and p.fell_back_from is None


def test_borrows_neighbour_group_instead_of_repeating(tmp_path):
    s = sel(tmp_path, [mk("f0", MoodGroup.FOCUS), mk("c0", MoodGroup.CHILL)])
    s.library.record_play("f0", 10 * HOUR)
    p = s.pick([MoodGroup.FOCUS], state(), now=10.5 * HOUR)
    assert p.song.uri == "c0" and p.fell_back_from == MoodGroup.FOCUS
    assert "Focus songs all played recently" in p.reason


def test_everything_recent_picks_least_recent_in_target(tmp_path):
    s = sel(tmp_path, [mk("f0", MoodGroup.FOCUS), mk("f1", MoodGroup.FOCUS)])
    s.library.record_play("f0", 10 * HOUR)
    s.library.record_play("f1", 9 * HOUR)
    p = s.pick([MoodGroup.FOCUS], state(), now=10.5 * HOUR)
    assert p.song.uri == "f1" and p.group == MoodGroup.FOCUS


def test_fresh_pick_respects_cooldown(tmp_path):
    s = sel(tmp_path, [mk("a", MoodGroup.UPBEAT), mk("b", MoodGroup.UPBEAT)])
    s.library.record_play("a", 1 * HOUR)
    s.library.record_play("b", 10 * HOUR)
    for _ in range(5):
        assert s.pick([MoodGroup.UPBEAT], state(), fresh=True, now=11 * HOUR).song.uri == "a"
