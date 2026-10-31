from PySide6.QtCore import QObject, Signal

from moodmusic.mood.groups import MoodGroup
from moodmusic.music.library import Song, SongLibrary
from moodmusic.music.scanner import ScanProgress
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


class FakeScan(QObject):
    progress = Signal(object)
    finished_with = Signal(object)

    def __init__(self, running=False):
        super().__init__()
        self.running, self.rescans = running, 0

    def is_running(self):
        return self.running

    def rescan(self):
        self.rescans += 1
        self.running = True


def test_review_scan_progress_and_rescan(qtbot, tmp_path):
    lb = lib(tmp_path)
    scan = FakeScan()
    d = ReviewDialog(lb, scan)
    qtbot.addWidget(d)
    assert d.rescan_button.isEnabled()
    d.rescan_button.click()
    assert scan.rescans == 1 and not d.rescan_button.isEnabled()
    scan.progress.emit(ScanProgress(1, 4, "Artist - Song"))
    assert "1/4" in d.scan_label.text()
    lb.upsert(Song("u9", "New", "Z", None, MoodGroup.FOCUS))
    scan.running = False
    scan.finished_with.emit(None)
    assert d.rescan_button.isEnabled() and d.lists[MoodGroup.FOCUS].count() == 1


def test_review_without_scan_hides_rescan(qtbot, tmp_path):
    d = ReviewDialog(lib(tmp_path))
    qtbot.addWidget(d)
    assert d.rescan_button.isHidden()
