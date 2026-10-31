"""Small modal dialog asking which of the five moods applies."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from moodmusic.mood.groups import MoodGroup

CHOICES = (MoodGroup.UPBEAT, MoodGroup.CHILL, MoodGroup.MELANCHOLY,
           MoodGroup.INTENSE, MoodGroup.FOCUS)


class MoodPicker(QDialog):
    def __init__(self, parent, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.choice: MoodGroup | None = None
        self.buttons: dict[MoodGroup, QPushButton] = {}
        self.setStyleSheet("QDialog { background:#1e1e24; } QLabel { color:#eee; }"
                           "QPushButton { background:#2d2d36; color:#eee; border:none;"
                           " border-radius:9px; padding:7px 14px; text-align:left; }"
                           "QPushButton:hover { background:#3a3a46; }")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(title))
        for group in CHOICES:
            btn = QPushButton(f"{group.emoji}  {group.label}")
            btn.clicked.connect(lambda _=False, g=group: self._pick(g))
            self.buttons[group] = btn
            lay.addWidget(btn)

    def _pick(self, group: MoodGroup) -> None:
        self.choice = group
        self.accept()

    @staticmethod
    def ask(parent, title: str) -> MoodGroup | None:
        dlg = MoodPicker(parent, title)
        return dlg.choice if dlg.exec() == QDialog.DialogCode.Accepted else None
