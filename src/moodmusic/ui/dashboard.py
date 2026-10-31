"""Advanced view: the song and your state first; settings at a glance; testing details folded."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from moodmusic.config import HOLD_SECONDS, Settings, save_settings
from moodmusic.mood.groups import MoodGroup
from moodmusic.ui.common import (BUTTON_CSS, CAMERA_MESSAGES, ArtLabel, DeviceButton,
                                 LoginButton, ModeToggle, StatusDot, media_button,
                                 set_play_state)
from moodmusic.ui.mood_picker import MoodPicker
from moodmusic.ui.state_panels import (EMOTION_NAMES, EmotionDeltas, SignalsPanel, StateBars,
                                       StateTimeline)

log = logging.getLogger(__name__)

EMOTIONS = EMOTION_NAMES
WINDOW_SECONDS = 3600
POSITIVE, ENERGY = QColor("#f7c948"), QColor("#4ad0a0")

CSS = """
QWidget { background:#1b1d22; color:#e8e8ea; font-size:12px; }
QPushButton { background:#30343c; border-radius:9px; padding:4px 10px; }
QPushButton:hover { background:#3a3f49; }
QFrame#card { background:#24272e; border-radius:8px; }
QFrame#card QLabel { background:transparent; }
QFrame#card QWidget#modes { background:transparent; }
QLabel#muted { color:#9aa0aa; font-size:11px; }
QLabel#state { font-size:24px; font-weight:600; }
QLabel#song { font-size:14px; font-weight:600; }
QPushButton#ctrl { background:#30343c; border-radius:17px; min-width:34px; max-width:34px;
                   min-height:34px; max-height:34px; font-size:15px; padding:0; }
QPushButton#play { background:#1db954; color:#000; border-radius:20px; min-width:40px;
                   max-width:40px; min-height:40px; max-height:40px; font-size:16px; padding:0; }
QPushButton#chip { background:#2b2f37; border:1px solid #3a3f49; border-radius:11px;
                   padding:3px 10px; font-size:11px; }
QPushButton#chip:hover { border-color:#1db954; }
QPushButton#fold { background:transparent; color:#9aa0aa; text-align:left; padding:2px 0; }
"""


def duration_text(since: float, now: float) -> str:
    minutes = int(max(0.0, now - since) // 60)
    return "just now" if minutes < 1 else f"for {minutes} min"


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 10)
    return frame, lay


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    return label


class MoodChart(QWidget):
    """Positive (valence) and energy (arousal) lines over the last hour."""
    def __init__(self, clock: Callable[[], float] = time.monotonic, parent=None) -> None:
        super().__init__(parent)
        self.history: list[tuple[float, float, float]] = []
        self._clock = clock
        self.setMinimumSize(240, 90)

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


class SettingsChips(QWidget):
    """Current settings at a glance. The song-switch chip toggles; the rest open Settings."""

    def __init__(self, engine, save: Callable[[Settings], None],
                 open_settings: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self._engine, self._save = engine, save
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.switch_chip = QPushButton()
        self.react_chip = QPushButton()
        self.away_chip = QPushButton()
        self.source_chip = QPushButton()
        self.chips = [self.switch_chip, self.react_chip, self.away_chip, self.source_chip]
        for chip in self.chips:
            chip.setObjectName("chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            lay.addWidget(chip)
        lay.addStretch(1)
        self.switch_chip.setToolTip("Click to change")
        self.switch_chip.clicked.connect(self._toggle_switch)
        for chip in self.chips[1:]:
            chip.setToolTip("Change in Settings")
            chip.clicked.connect(lambda _=False: open_settings())
        self.refresh()

    def _toggle_switch(self) -> None:
        s = self._engine.settings
        s.switch_mode = "wait" if s.switch_mode == "immediate" else "immediate"
        try:
            self._save(s)
        except Exception:
            log.exception("Could not save settings")
        self.refresh()

    def refresh(self) -> None:
        s = self._engine.settings
        self.switch_chip.setText("On mood change: "
                                 + ("switch now" if s.switch_mode == "immediate"
                                    else "finish song"))
        hold = HOLD_SECONDS.get(s.sensitivity, HOLD_SECONDS["normal"])
        self.react_chip.setText(f"Reacts after: {hold} s")
        self.away_chip.setText("Away pause: "
                               + (f"{s.away_pause_minutes} min" if s.away_pause_minutes
                                  else "off"))
        self.source_chip.setText("Plays from: "
                                 + ("Liked Songs" if s.source_playlist_id is None
                                    else "a playlist"))


class Dashboard(QWidget):
    switch_view = Signal(str)
    settings_requested = Signal()
    review_requested = Signal()
    login_requested = Signal()

    def __init__(self, engine, worker, clock: Callable[[], float] = time.monotonic,
                 save: Callable[[Settings], None] = save_settings, baselines=None) -> None:
        super().__init__()
        self._engine, self._worker, self._clock = engine, worker, clock
        self._mood = None
        self.setWindowTitle("Mood Music")
        self.resize(760, 640)
        self.setStyleSheet(BUTTON_CSS + CSS)

        # -- your state ------------------------------------------------------
        state_card, sl = _card()
        sl.addWidget(_muted("You seem"))
        self.state_label = QLabel("…")
        self.state_label.setObjectName("state")
        self.state_detail = _muted("Reading your face…")
        self.state_detail.setWordWrap(True)
        self.feel_btn = QPushButton("Not how I feel")
        self.feel_btn.clicked.connect(self._not_how_i_feel)
        sl.addWidget(self.state_label)
        sl.addWidget(self.state_detail)
        sl.addStretch(1)
        feel_row = QHBoxLayout()
        feel_row.addWidget(self.feel_btn)
        feel_row.addStretch(1)
        sl.addLayout(feel_row)

        # -- now playing -----------------------------------------------------
        song_card, pl = _card()
        self.art = ArtLabel(56)
        self.song_label = QLabel("Nothing playing")
        self.song_label.setObjectName("song")
        self.song_label.setWordWrap(True)
        self.artist_label = _muted("")
        self.reason_label = _muted("")
        self.reason_label.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(self.art, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        for w in (self.song_label, self.artist_label, self.reason_label):
            texts.addWidget(w)
        top.addLayout(texts, 1)
        pl.addLayout(top)
        self.prev_btn = media_button("prev", "Previous song")
        self.pause_btn = media_button("play", "Play", "#000000")
        self.next_btn = media_button("next", "Next song")
        controls = QHBoxLayout()
        for btn, name, slot in ((self.prev_btn, "ctrl", engine.previous),
                                (self.pause_btn, "play", engine.toggle_pause),
                                (self.next_btn, "ctrl", engine.skip)):
            btn.setObjectName(name)
            btn.setIconSize(QSize(22, 22) if name == "play" else QSize(18, 18))
            btn.clicked.connect(lambda _=False, s=slot: s())
            controls.addWidget(btn)
        controls.addStretch(1)
        self.wrong_btn = QPushButton("Wrong vibe")
        self.wrong_btn.clicked.connect(self._wrong_vibe)
        self.device_btn = DeviceButton(engine)
        self.login_btn = LoginButton(engine, self.login_requested.emit)
        for b in (self.device_btn, self.login_btn, self.wrong_btn):
            controls.addWidget(b)
        pl.addLayout(controls)

        hero = QHBoxLayout()
        hero.addWidget(state_card, 4)
        hero.addWidget(song_card, 5)

        # -- how sure about each state + last hour ---------------------------
        bars_card, bl = _card()
        head = QHBoxLayout()
        head.addWidget(_muted("How sure it is about each state  ·  "
                              "<span style='color:#f7c948'>│</span> needed to switch"), 1)
        self.mode_toggle = ModeToggle(engine, save)
        self.mode_toggle.setObjectName("modes")
        head.addWidget(self.mode_toggle)
        bl.addLayout(head)
        self.state_bars = StateBars()
        bl.addWidget(self.state_bars)
        bl.addWidget(_muted("Last hour"))
        self.timeline = StateTimeline(clock)
        bl.addWidget(self.timeline)

        self.chips = SettingsChips(engine, save, self.settings_requested.emit)

        # -- testing details (folded) ----------------------------------------
        self.testing_toggle = QPushButton("▸ Show camera, face signals and emotions (testing)")
        self.testing_toggle.setObjectName("fold")
        self.testing_toggle.setCheckable(True)
        self.testing_toggle.toggled.connect(self._fold)
        self.testing = QWidget()
        tl = QHBoxLayout(self.testing)
        tl.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel("Camera preview")
        self.preview_label.setFixedSize(240, 180)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background:#333; border-radius:6px; color:#aaa;")
        tl.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignTop)
        det = QVBoxLayout()
        det.addWidget(_muted("Emotions compared with your resting face"))
        self.emotions = EmotionDeltas()
        self.emotions.set_rest(getattr(getattr(worker, "baseline", None), "probs", None))
        det.addWidget(self.emotions)
        det.addWidget(_muted("Face signals  (tick = your normal)"))
        self.signals = SignalsPanel(baselines)
        det.addWidget(self.signals)
        det.addWidget(_muted("<span style='color:#f7c948'>■</span> positive  "
                             "<span style='color:#4ad0a0'>■</span> energy, last hour"))
        self.chart = MoodChart(clock)
        det.addWidget(self.chart)
        tl.addLayout(det, 1)
        self.testing.setVisible(False)

        # -- footer ------------------------------------------------------------
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

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(10)
        root.addLayout(hero)
        root.addWidget(bars_card)
        root.addWidget(self.chips)
        root.addWidget(self.testing_toggle)
        root.addWidget(self.testing)
        root.addStretch(1)
        root.addLayout(bottom)

        engine.listeners.append(self.refresh)
        worker.reading.connect(self._on_reading)
        worker.preview.connect(self._on_preview)
        worker.mood.connect(self._on_mood)
        worker.camera_status.connect(self._on_camera_status)
        worker.features_ready.connect(self.signals.set_features)
        worker.scores_ready.connect(self.state_bars.set_scores)
        worker.calibration_done.connect(self._on_calibrated)
        self.refresh()

    # ---- worker inputs -------------------------------------------------------
    def _on_reading(self, reading) -> None:
        self.emotions.set_probs(reading.probs)

    def _on_calibrated(self, baseline) -> None:
        self.emotions.set_rest(getattr(baseline, "probs", None))

    def _on_preview(self, image) -> None:
        self.preview_label.setPixmap(QPixmap.fromImage(image).scaled(
            self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _on_mood(self, mood) -> None:
        self._mood = mood
        self.state_bars.set_current(mood.state)
        self.timeline.add(self._clock(), mood.state)
        self._show_state()

    def _show_state(self) -> None:
        mood = self._mood
        if mood is None:
            return
        self.state_label.setText(f"{mood.state.emoji} {mood.state.label}")
        detail = duration_text(mood.since, self._clock())
        self.state_detail.setText(f"{detail} · {mood.reason}" if mood.reason else detail)

    def _on_camera_status(self, status: str) -> None:
        if status != "ok":
            self.preview_label.clear()
            self.preview_label.setText(CAMERA_MESSAGES.get(status, ("", f"Camera: {status}"))[1])

    def _fold(self, shown: bool) -> None:
        self.testing.setVisible(shown)
        self.testing_toggle.setText(("▾ Hide" if shown else "▸ Show")
                                    + " camera, face signals and emotions (testing)")

    # ---- engine state ----------------------------------------------------------
    def refresh(self) -> None:
        status = self._engine.status
        self.dot.set_status(status.kind, status.message)
        self.status_label.setText(status.message or "All good")
        pick = self._engine.current_pick
        if pick is None:
            self.song_label.setText("Nothing playing")
            self.artist_label.setText("")
            self.reason_label.setText("")
        else:
            self.song_label.setText(pick.song.title)
            group = pick.song.group
            tag = f" · {group.emoji} {group.value.capitalize()}" if isinstance(
                group, MoodGroup) else ""
            self.artist_label.setText(f"{pick.song.artist}{tag}")
            self.reason_label.setText(f"Picked because {pick.reason}")
        self.art.set_url(pick.song.album_art if pick else None)
        self.wrong_btn.setEnabled(pick is not None)
        set_play_state(self.pause_btn, bool(getattr(self._engine, "is_playing", False)),
                       "#000000")
        self.chart.set_history(self._engine.history)
        self.mode_toggle.refresh()
        self.device_btn.refresh()
        self.login_btn.refresh()
        self.chips.refresh()
        self._show_state()

    # ---- user actions ----------------------------------------------------------
    def _not_how_i_feel(self) -> None:
        state = MoodPicker.ask_state(self, "How do you feel?")
        if state is not None:
            self._worker.force_mood(state)

    def _wrong_vibe(self) -> None:
        group = MoodPicker.ask_group(self, "This song fits…")
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
