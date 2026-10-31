"""Full dashboard window (mockup B)."""
from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from moodmusic.config import Settings, save_settings
from moodmusic.ui.common import (BUTTON_CSS, ArtLabel, DeviceButton, ModeToggle, StatusDot)
from moodmusic.ui.mood_picker import MoodPicker

EMOTIONS = ("anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise")
BAR_COLORS = {"happiness": "#f7c948", "neutral": "#888888", "sadness": "#4a7bd0",
              "fear": "#9b6bd0", "anger": "#e5484d", "disgust": "#6a994e",
              "contempt": "#c77d4a", "surprise": "#4ad0a0"}
WINDOW_SECONDS = 3600
POSITIVE, ENERGY = QColor("#f7c948"), QColor("#4ad0a0")


class MoodChart(QWidget):
    """Positive (valence) and energy (arousal) lines over the last hour."""
    def __init__(self, clock: Callable[[], float] = time.monotonic, parent=None) -> None:
        super().__init__(parent)
        self.history: list[tuple[float, float, float]] = []
        self._clock = clock
        self.setMinimumSize(240, 110)

    def set_history(self, history) -> None:
        self.history = list(history)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#222229"))
        p.setPen(QPen(QColor("#3a3a46"), 1))
        p.drawLine(0, h // 2, w, h // 2)
        now = self._clock()
        points = [(t, v, a) for t, v, a in self.history if now - t <= WINDOW_SECONDS]
        for idx, colour in ((1, POSITIVE), (2, ENERGY)):
            p.setPen(QPen(colour, 2))
            prev = None
            for item in points:
                x = (item[0] - (now - WINDOW_SECONDS)) / WINDOW_SECONDS * w
                y = (1 - (max(-1.0, min(1.0, item[idx])) + 1) / 2) * (h - 6) + 3
                if prev is not None:
                    p.drawLine(int(prev[0]), int(prev[1]), int(x), int(y))
                prev = (x, y)


class Dashboard(QWidget):
    switch_view = Signal(str)
    settings_requested = Signal()
    review_requested = Signal()

    def __init__(self, engine, worker, clock: Callable[[], float] = time.monotonic,
                 save: Callable[[Settings], None] = save_settings) -> None:
        super().__init__()
        self._engine, self._worker = engine, worker
        self.setWindowTitle("Mood Music")
        self.resize(720, 420)
        self.setStyleSheet("QWidget { background:#16161b; color:#eee; }" + BUTTON_CSS
                           + "QProgressBar { background:#2a2a32; border:none; border-radius:3px;"
                             " max-height:6px; }")

        self.preview_label = QLabel("Camera preview")
        self.preview_label.setFixedSize(320, 240)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background:#333; border-radius:6px; color:#aaa;")
        self.bars: dict[str, QProgressBar] = {}
        left = QVBoxLayout()
        left.addWidget(self.preview_label)
        for name in EMOTIONS:
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"QProgressBar::chunk {{ background:{BAR_COLORS[name]};"
                              " border-radius:3px; }")
            self.bars[name] = bar
            row = QHBoxLayout()
            label = QLabel(name.capitalize())
            label.setFixedWidth(70)
            row.addWidget(label)
            row.addWidget(bar, 1)
            left.addLayout(row)
        left.addStretch(1)

        self.chart = MoodChart(clock)
        legend = QLabel('<span style="color:#f7c948">■</span> positive '
                        '<span style="color:#4ad0a0">■</span> energy')
        legend.setStyleSheet("font-size:10px; color:#aaa;")
        self.art = ArtLabel(48)
        self.song_label = QLabel("Nothing playing")
        self.song_label.setStyleSheet("font-weight:bold;")
        self.reason_label = QLabel("")
        self.reason_label.setStyleSheet("color:#999; font-size:11px;")
        self.reason_label.setWordWrap(True)
        playing = QHBoxLayout()
        playing.addWidget(self.art)
        texts = QVBoxLayout()
        texts.addWidget(self.song_label)
        texts.addWidget(self.reason_label)
        playing.addLayout(texts, 1)
        self.wrong_btn = QPushButton("Wrong vibe")
        self.wrong_btn.clicked.connect(self._wrong_vibe)
        self.mode_toggle = ModeToggle(engine, save)
        self.device_btn = DeviceButton(engine)
        self.mood_label = QLabel("")
        modes = QHBoxLayout()
        modes.addWidget(self.mood_label, 1)
        modes.addWidget(self.mode_toggle)
        right = QVBoxLayout()
        right.addWidget(QLabel("Mood over the last hour"))
        right.addWidget(self.chart)
        right.addWidget(legend)
        right.addLayout(playing)
        right.addWidget(self.wrong_btn)
        right.addWidget(self.device_btn)
        right.addLayout(modes)
        right.addStretch(1)

        self.dot = StatusDot()
        self.status_label = QLabel("All good")
        self.settings_btn = QPushButton("Settings")
        self.review_btn = QPushButton("Review songs")
        self.simple_btn = QPushButton("Simple view")
        self.settings_btn.clicked.connect(self.settings_requested)
        self.review_btn.clicked.connect(self.review_requested)
        self.simple_btn.clicked.connect(lambda: self.switch_view.emit("simple"))
        bottom = QHBoxLayout()
        bottom.addWidget(self.dot)
        bottom.addWidget(self.status_label, 1)
        for b in (self.settings_btn, self.review_btn, self.simple_btn):
            bottom.addWidget(b)

        body = QHBoxLayout()
        body.addLayout(left)
        body.addLayout(right, 1)
        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addLayout(bottom)

        engine.listeners.append(self.refresh)
        worker.reading.connect(self._on_reading)
        worker.preview.connect(self._on_preview)
        worker.mood.connect(self._on_mood)
        worker.camera_status.connect(self._on_camera_status)
        self.refresh()

    def _on_reading(self, reading) -> None:
        for name, bar in self.bars.items():
            bar.setValue(int(round(reading.probs.get(name, 0.0) * 100)))

    def _on_preview(self, image) -> None:
        self.preview_label.setPixmap(QPixmap.fromImage(image).scaled(
            self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _on_mood(self, state) -> None:
        self.mood_label.setText(f"{state.group.emoji} {state.group.label}")

    def _on_camera_status(self, status: str) -> None:
        if status != "ok":
            self.preview_label.clear()
            self.preview_label.setText(f"Camera: {status}")

    def refresh(self) -> None:
        status = self._engine.status
        self.dot.set_status(status.kind, status.message)
        self.status_label.setText(status.message or "All good")
        pick = self._engine.current_pick
        if pick is None:
            self.song_label.setText("Nothing playing")
            self.reason_label.setText("")
        else:
            self.song_label.setText(f"▶ {pick.song.title} · {pick.song.artist}")
            self.reason_label.setText(f"picked because: {pick.reason}")
        self.art.set_url(pick.song.album_art if pick else None)
        self.wrong_btn.setEnabled(pick is not None)
        self.chart.set_history(self._engine.history)
        self.mode_toggle.refresh()
        self.device_btn.refresh()

    def _wrong_vibe(self) -> None:
        group = MoodPicker.ask(self, "This song fits…")
        if group is not None:
            self._engine.wrong_vibe(group)

    def showEvent(self, event) -> None:
        self._worker.set_preview(True)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._worker.set_preview(False)
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
