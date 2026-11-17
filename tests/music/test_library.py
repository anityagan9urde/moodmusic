from moodmusic.mood.groups import MoodGroup
from moodmusic.music.library import Song, SongLibrary


def mk(uri, group=MoodGroup.CHILL, **kw):
    d = dict(uri=uri, title="T" + uri, artist="A", album_art=None, group=group,
             tags=["x", "y"], source="track", override=False)
    d.update(kw)
    return Song(**d)


def test_roundtrip(tmp_path):
    lib = SongLibrary(tmp_path / "sub" / "l.db")
    s = mk("u1", album_art="http://a")
    lib.upsert(s)
    assert lib.get("u1") == s
    assert lib.get("nope") is None


def test_set_group_sets_override(tmp_path):
    lib = SongLibrary(tmp_path / "l.db")
    lib.upsert(mk("u1"))
    lib.set_group("u1", MoodGroup.INTENSE)
    s = lib.get("u1")
    assert s.group == MoodGroup.INTENSE and s.override is True


def test_override_survives_rescan(tmp_path):
    lib = SongLibrary(tmp_path / "l.db")
    lib.upsert(mk("u1"))
    lib.set_group("u1", MoodGroup.INTENSE)
    lib.upsert(mk("u1", group=MoodGroup.UPBEAT, title="New", tags=["z"]))
    s = lib.get("u1")
    assert s.group == MoodGroup.INTENSE and s.override is True
    assert s.title == "New" and s.tags == ["z"]


def test_counts_remove_songs_uris(tmp_path):
    lib = SongLibrary(tmp_path / "l.db")
    lib.upsert(mk("a"))
    lib.upsert(mk("b"))
    lib.upsert(mk("c", group=MoodGroup.UPBEAT))
    assert lib.counts()[MoodGroup.CHILL] == 2
    assert lib.counts()[MoodGroup.UPBEAT] == 1
    assert lib.counts().get(MoodGroup.FOCUS, 0) == 0
    assert lib.uris() == {"a", "b", "c"}
    assert len(lib.songs()) == 3
    assert {s.uri for s in lib.songs(MoodGroup.CHILL)} == {"a", "b"}
    lib.remove({"a", "c"})
    assert lib.uris() == {"b"}


def test_survives_reopen(tmp_path):
    p = tmp_path / "l.db"
    lib = SongLibrary(p)
    lib.upsert(mk("u1"))
    lib.close()
    assert SongLibrary(p).get("u1") is not None


def test_play_history_roundtrip(tmp_path):
    lib = SongLibrary(tmp_path / "h.db")
    assert lib.last_played() == {}
    lib.record_play("u1", 10.0)
    lib.record_play("u1", 20.0)
    lib.record_play("u2", 15.0)
    lib.close()
    lib = SongLibrary(tmp_path / "h.db")
    assert lib.last_played() == {"u1": 20.0, "u2": 15.0}


def test_clear_override_lets_scans_regroup(tmp_path):
    lib = SongLibrary(tmp_path / "o.db")
    lib.upsert(Song("u1", "T", "A", None, MoodGroup.CHILL, [], "track", False))
    lib.set_group("u1", MoodGroup.PARTY, by_user=True)
    lib.clear_override("u1")
    s = lib.get("u1")
    assert not s.override and s.source == "none"
    lib.upsert(Song("u1", "T", "A", None, MoodGroup.UPBEAT, [], "track", False))
    assert lib.get("u1").group == MoodGroup.UPBEAT  # a rescan may now regroup it
