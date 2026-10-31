"""Song review: drag songs between mood groups to correct them."""
from __future__ import annotations

import logging

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from moodmusic.mood.groups import MoodGroup
from moodmusic.music.library import Song, SongLibrary
from moodmusic.music.scanner import suggest_group

log = logging.getLogger(__name__)
URI_ROLE = Qt.ItemDataRole.UserRole


class GroupList(QListWidget):
    """Drag source and drop target; the owning dialog performs the move."""

    def __init__(self, group: MoodGroup, dialog: "ReviewDialog") -> None:
        super().__init__()
        self.group, self._dialog = group, dialog
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.IgnoreAction)

    def mimeData(self, items) -> QMimeData:  # noqa: N802
        mime = QMimeData()
        mime.setText("\n".join(i.data(URI_ROLE) for i in items))
        return mime

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        e.acceptProposedAction() if e.mimeData().hasText() else e.ignore()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        e.acceptProposedAction() if e.mimeData().hasText() else e.ignore()

    def dropEvent(self, e) -> None:  # noqa: N802
        uris = e.mimeData().text().splitlines()
        e.setDropAction(Qt.DropAction.IgnoreAction)  # the dialog rebuilds the lists itself
        e.accept()
        # Deferred: rebuilding the source list while its drag is still unwinding is unsafe.
        QTimer.singleShot(0, lambda: [self._dialog.move_song(u, self.group) for u in uris])


class ReviewDialog(QDialog):
    def __init__(self, library: SongLibrary, parent=None) -> None:
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Review songs")
        self.resize(900, 560)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("Drag songs between lists to fix their mood. "
                               "Your choices are remembered when the library is rescanned."))
        grid = QGridLayout()
        outer.addLayout(grid)
        self.lists: dict[MoodGroup, GroupList] = {}
        for n, group in enumerate(MoodGroup):
            box = QVBoxLayout()
            box.addWidget(QLabel(f"{group.emoji} {group.label}"))
            lst = GroupList(group, self)
            self.lists[group] = lst
            box.addWidget(lst)
            grid.addLayout(box, n // 3, n % 3)
        self._songs: dict[str, Song] = {}
        self._suggestions: dict[str, MoodGroup | None] = {}
        self.refresh()

    def suggestion(self, uri: str) -> MoodGroup | None:
        return self._suggestions.get(uri)

    def item_text(self, uri: str) -> str:
        for lst in self.lists.values():
            for i in range(lst.count()):
                item = lst.item(i)
                if item.data(URI_ROLE) == uri:
                    w = lst.itemWidget(item)
                    return w.text_label.text() if w else item.text()
        return ""

    def refresh(self) -> None:
        for lst in self.lists.values():
            lst.clear()
        self._songs, self._suggestions = {}, {}
        for song in sorted(self.library.songs(), key=lambda s: (s.artist.lower(), s.title.lower())):
            self._songs[song.uri] = song
            lst = self.lists[song.group]
            item = QListWidgetItem()
            item.setData(URI_ROLE, song.uri)
            text = f"{song.title} - {song.artist}"
            if song.group == MoodGroup.UNSORTED:
                sug = suggest_group(song, self.library)
                self._suggestions[song.uri] = sug
                if sug is not None:
                    lst.addItem(item)
                    self._set_suggestion_widget(lst, item, text, sug, song.uri)
                    continue
            item.setText(text)
            lst.addItem(item)

    def _set_suggestion_widget(self, lst, item, text, sug, uri) -> None:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(2, 2, 2, 2)
        row.text_label = QLabel(f"{text}\nSuggested: {sug.label}")
        row.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(row.text_label, 1)
        btn = QPushButton("Accept")
        btn.clicked.connect(lambda: self.accept_suggestion(uri))
        lay.addWidget(btn)
        item.setSizeHint(row.sizeHint())
        lst.setItemWidget(item, row)

    def move_song(self, uri: str, group: MoodGroup) -> None:
        song = self._songs.get(uri)
        if song is None or song.group == group:
            return
        self.library.set_group(uri, group, by_user=True)
        self.refresh()

    def accept_suggestion(self, uri: str) -> None:
        sug = self._suggestions.get(uri)
        if sug is not None:
            self.move_song(uri, sug)
