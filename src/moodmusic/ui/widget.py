"""Small always-on-top floating widget (mockup A)."""
from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from moodmusic.config import Settings, save_settings
from moodmusic.ui.common import (BG, BUTTON_CSS, ArtLabel, DeviceButton,
                                 LoginButton, ModeToggle, StatusDot, steady_text)
from moodmusic.ui.mood_picker import MoodPicker


class MoodWidget(QWidget):
    switch_view = Signal(str)
    login_requested = Signal()

    def __init__(self, engine, worker, clock: Callable[[], float] = time.monotonic,
                 save: Callable[[Settings], None] = save_settings) -> None:
        super().__init__()
        self._engine, self._worker, self._clock = engine, worker, clock
        self._mood = None
        self._quality = None
        self._drag = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(290, 150)
        self.setStyleSheet(BUTTON_CSS + "QLabel { color:#eee; }")

        self.mood_label = QLabel("…")
        self.mood_label.setStyleSheet("font-size:13px; font-weight:bold;")
        self.steady_label = QLabel("")
        self.steady_label.setStyleSheet("font-size:11px; color:#aaa;")
        self.mode_toggle = ModeToggle(engine, save)
        self.dot = StatusDot()
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.mood_label)
        col.addWidget(self.steady_label)
        top.addLayout(col, 1)
        top.addWidget(self.mode_toggle)
        top.addWidget(self.dot)

        self.art = ArtLabel(34)
        self.title_label = QLabel("Nothing playing")
        self.title_label.setStyleSheet("font-size:11px; font-weight:bold;")
        self.artist_label = QLabel("")
        self.artist_label.setStyleSheet("font-size:11px; color:#aaa;")
        self.prev_btn, self.pause_btn, self.next_btn = (
            QPushButton("⏮"), QPushButton("⏸"), QPushButton("⏭"))
        song = QHBoxLayout()
        song.addWidget(self.art)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(self.title_label)
        text.addWidget(self.artist_label)
        song.addLayout(text, 1)
        for btn, slot in ((self.prev_btn, engine.previous), (self.pause_btn, engine.toggle_pause),
                          (self.next_btn, engine.skip)):
            btn.setObjectName("flat")
            btn.clicked.connect(lambda _=False, s=slot: s())
            song.addWidget(btn)

        self.feel_btn = QPushButton("Not how I feel")
        self.wrong_btn = QPushButton("Wrong vibe")
        self.advanced_btn = QPushButton("Advanced ⤢")
        self.device_btn = DeviceButton(engine)
        self.login_btn = LoginButton(engine, self.login_requested.emit)
        self.feel_btn.clicked.connect(self._not_how_i_feel)
        self.wrong_btn.clicked.connect(self._wrong_vibe)
        self.advanced_btn.clicked.connect(lambda: self.switch_view.emit("advanced"))
        actions = QHBoxLayout()
        actions.setSpacing(4)
        for b in (self.feel_btn, self.wrong_btn, self.device_btn, self.login_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.advanced_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.addLayout(top)
        root.addLayout(song)
        root.addLayout(actions)

        engine.listeners.append(self.refresh)
        worker.mood.connect(self._on_mood)
        worker.quality.connect(self._on_quality)
        self.refresh()

    # ---- state ----------------------------------------------------------
    def _on_mood(self, state) -> None:
        self._mood = state
        self.refresh()

    def _on_quality(self, report) -> None:
        self._quality = report
        self.refresh()

    def refresh(self) -> None:
        status = self._engine.status
        bad_quality = self._quality is not None and not self._quality.ok
        if bad_quality:
            self.mood_label.setText(self._quality.issue or "Poor image quality")
            self.steady_label.setText("")
        elif self._mood is not None:
            self.mood_label.setText(f"{self._mood.group.emoji} {self._mood.group.label}")
            self.steady_label.setText(steady_text(self._mood.since, self._clock()))
        if bad_quality and status.kind == "ok":
            self.dot.set_status("warning", self._quality.issue or "")
        else:
            self.dot.set_status(status.kind, status.message)
        pick = self._engine.current_pick
        self.title_label.setText(pick.song.title if pick else "Nothing playing")
        self.artist_label.setText(pick.song.artist if pick else "")
        self.art.set_url(pick.song.album_art if pick else None)
        self.wrong_btn.setEnabled(pick is not None)
        self.mode_toggle.refresh()
        self.device_btn.refresh()
        self.login_btn.refresh()

    # ---- actions ----------------------------------------------------------
    def _not_how_i_feel(self) -> None:
        # Routed through the worker (records the correction, resets the smoother).
        group = MoodPicker.ask(self, "How do you feel?")
        if group is not None:
            self._worker.force_mood(group)

    def _wrong_vibe(self) -> None:
        group = MoodPicker.ask(self, "This song fits…")
        if group is not None:
            self._engine.wrong_vibe(group)

    # ---- window behaviour ---------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(BG))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), 14, 14)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None
