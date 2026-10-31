from moodmusic.mood.groups import MoodGroup
from moodmusic.music.library import Song, SongLibrary
from moodmusic.ui.review_dialog import ReviewDialog


def lib(tmp_path):
    lb = SongLibrary(tmp_path / "l.db")
    lb.upsert(Song("u1", "A", "Artist X", None, MoodGroup.CHILL))
    lb.upsert(Song("u2", "B", "Artist X", None, MoodGroup.UNSORTED))
    lb.upsert(Song("u3", "C", "Other", None, MoodGroup.UNSORTED))
    return lb


def test_review_drag_sets_override(qtbot, tmp_path):
    lb = lib(tmp_path)
    d = ReviewDialog(lb)
    qtbot.addWidget(d)
    assert d.lists[MoodGroup.CHILL].count() == 1
    d.move_song("u1", MoodGroup.INTENSE)
    s = lb.get("u1")
    assert s.group == MoodGroup.INTENSE and s.override and s.source == "user"
    assert d.lists[MoodGroup.INTENSE].count() == 1 and d.lists[MoodGroup.CHILL].count() == 0
    lb.close()


def test_unsorted_accept_suggestion(qtbot, tmp_path):
    lb = lib(tmp_path)
    d = ReviewDialog(lb)
    qtbot.addWidget(d)
    assert d.suggestion("u2") == MoodGroup.CHILL
    assert d.suggestion("u3") is None
    assert "Suggested: Chill" in d.item_text("u2")
    d.accept_suggestion("u2")
    assert lb.get("u2").group == MoodGroup.CHILL and lb.get("u2").override
    assert d.lists[MoodGroup.UNSORTED].count() == 1
    lb.close()
