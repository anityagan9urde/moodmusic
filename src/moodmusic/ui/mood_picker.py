"""Small modal dialog: pick a face state ("Not how I feel") or a song group ("Wrong vibe")."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.states import FaceState

STATE_CHOICES = tuple(FaceState)
GROUP_CHOICES = tuple(g for g in MoodGroup if g != MoodGroup.UNSORTED)


class MoodPicker(QDialog):
    """Buttons for each choice; anything with .emoji and .label works (states or groups)."""

    def __init__(self, parent, title: str, choices) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.choice = None
        self.buttons: dict = {}
        self.setStyleSheet("QDialog { background:#1e1e24; } QLabel { color:#eee; }"
                           "QPushButton { background:#2d2d36; color:#eee; border:none;"
                           " border-radius:9px; padding:7px 14px; text-align:left; }"
                           "QPushButton:hover { background:#3a3a46; }")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(title))
        for item in choices:
            btn = QPushButton(f"{item.emoji}  {item.label}")
            btn.clicked.connect(lambda _=False, c=item: self._pick(c))
            self.buttons[item] = btn
            lay.addWidget(btn)

    def _pick(self, choice) -> None:
        self.choice = choice
        self.accept()

    @staticmethod
    def _ask(parent, title: str, choices):
        dlg = MoodPicker(parent, title, choices)
        return dlg.choice if dlg.exec() == QDialog.DialogCode.Accepted else None

    @staticmethod
    def ask_state(parent, title: str) -> FaceState | None:
        return MoodPicker._ask(parent, title, STATE_CHOICES)

    @staticmethod
    def ask_group(parent, title: str) -> MoodGroup | None:
        return MoodPicker._ask(parent, title, GROUP_CHOICES)
