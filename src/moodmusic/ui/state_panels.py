"""Dashboard pieces that explain the face state: live signals vs baseline, state timeline."""
from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from moodmusic.mood.baselines import PersonalBaselines
from moodmusic.mood.features import Features
from moodmusic.mood.states import FaceState

WINDOW_SECONDS = 3600
STILLNESS_REF_S = 10.0  # marker for stillness: 10 s without moving
STATE_COLORS = {
    FaceState.FOCUSED: "#4a7bd0", FaceState.DEEP_THOUGHT: "#7a5cd0", FaceState.LOVE: "#e05a9a",
    FaceState.TIRED: "#8a8a6a", FaceState.SLEEPY: "#5a6a8a", FaceState.STRESSED: "#e5484d",
    FaceState.BORED: "#888888", FaceState.HAPPY: "#f7c948", FaceState.EXCITED: "#f08a24",
    FaceState.SAD: "#3a6aa0",
}


def _pct(x: float) -> int:
    return int(round(max(0.0, min(1.0, x)) * 100))


def signal_values(f: Features) -> dict[str, int]:
    """0-100 bars for the signals that drive the state rules."""
    return {
        "Eyes on screen": _pct(f.gaze_on_ratio_30s),
        "Blink rate": _pct(f.blink_rate_per_min_60s / 60.0),
        "Stillness": _pct(f.stillness_s / 30.0),
        "Smile": _pct(f.smile_10s),
        "Tension": _pct((f.brow_down_30s + f.mouth_press_30s) / 2),
        "Eyes open": _pct(1.0 - f.perclos_60s),
    }


def baseline_markers(b: PersonalBaselines) -> dict[str, int]:
    """Where 'normal for you' sits on each bar."""
    return {
        "Eyes on screen": _pct(b.get("gaze_on_ratio_30s")),
        "Blink rate": _pct(b.get("blink_rate_per_min_60s") / 60.0),
        "Stillness": _pct(STILLNESS_REF_S / 30.0),
        "Smile": _pct(b.get("smile_10s")),
        "Tension": _pct((b.get("brow_down_30s") + b.get("mouth_press_30s")) / 2),
        "Eyes open": _pct(1.0 - b.get("perclos_60s")),
    }


class SignalsPanel(QWidget):
    """One bar per signal with a tick for the user's own baseline."""

    def __init__(self, baselines: PersonalBaselines | None = None, parent=None) -> None:
        super().__init__(parent)
        self._baselines = baselines or PersonalBaselines()
        self.values: dict[str, int] = {k: 0 for k in signal_values(Features())}
        self.markers: dict[str, int] = baseline_markers(self._baselines)
        self.setMinimumHeight(18 * len(self.values))

    def set_features(self, f: Features) -> None:
        self.values = signal_values(f)
        self.markers = baseline_markers(self._baselines)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        row = max(14, self.height() // max(1, len(self.values)))
        label_w, w = 96, self.width()
        bar_w = max(10, w - label_w - 6)
        for i, (name, value) in enumerate(self.values.items()):
            y = i * row
            p.setPen(QColor("#bbbbbb"))
            p.drawText(0, y, label_w, row, Qt.AlignmentFlag.AlignVCenter, name)
            p.fillRect(label_w, y + row // 3, bar_w, row // 3, QColor("#2a2a32"))
            p.fillRect(label_w, y + row // 3, bar_w * value // 100, row // 3, QColor("#4ad0a0"))
            mx = label_w + bar_w * self.markers.get(name, 0) // 100
            p.setPen(QPen(QColor("#f7c948"), 2))
            p.drawLine(mx, y + row // 4, mx, y + row - row // 4)


class StateTimeline(QWidget):
    """Coloured strip of face states over the last hour, one segment per change."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, parent=None) -> None:
        super().__init__(parent)
        self._clock = clock
        self.segments: list[tuple[float, FaceState]] = []
        self.setMinimumHeight(16)

    def add(self, t: float, state: FaceState) -> None:
        if self.segments and self.segments[-1][1] == state:
            return
        self.segments.append((t, state))
        while len(self.segments) > 1 and t - self.segments[1][0] > WINDOW_SECONDS:
            self.segments.pop(0)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor("#222229"))
        now = self._clock()
        start = now - WINDOW_SECONDS
        for i, (t, state) in enumerate(self.segments):
            end = self.segments[i + 1][0] if i + 1 < len(self.segments) else now
            x0 = int((max(t, start) - start) / WINDOW_SECONDS * w)
            x1 = int((end - start) / WINDOW_SECONDS * w)
            if x1 > x0:
                p.fillRect(x0, 0, x1 - x0, h, QColor(STATE_COLORS[state]))


DECIDE_LINE = 60  # % a state needs before it can take over (rules.DECIDE_MIN)
EMOTION_NAMES = ("anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness",
                 "surprise")
REST_BAND = 5  # within this many points of the resting face reads as "≈ rest"


class StateBars(QWidget):
    """One bar per face state: how sure the rules are, with the take-over line marked."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.values: dict[FaceState, int] = {s: 0 for s in FaceState}
        self.current: FaceState | None = None
        self.setMinimumHeight(19 * len(self.values))

    def set_scores(self, scores: dict) -> None:
        self.values = {s: _pct(scores.get(s, 0.0)) for s in FaceState}
        self.update()

    def set_current(self, state: FaceState) -> None:
        self.current = state
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.values)
        row = max(16, self.height() // max(1, n))
        label_w, value_w = 130, 40
        bar_w = max(10, self.width() - label_w - value_w - 8)
        for i, (state, value) in enumerate(self.values.items()):
            y = i * row
            on = state == self.current
            p.setPen(QColor("#ffffff" if on else "#c8c8cc"))
            p.drawText(0, y, label_w, row, Qt.AlignmentFlag.AlignVCenter,
                       f"{state.emoji}  {state.label}")
            top, h = y + row // 2 - 4, 8
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#30343c"))
            p.drawRoundedRect(label_w, top, bar_w, h, 4, 4)
            if value:
                p.setBrush(QColor("#1db954" if on else "#5b8def"))
                p.drawRoundedRect(label_w, top, max(h, bar_w * value // 100), h, 4, 4)
            mx = label_w + bar_w * DECIDE_LINE // 100
            p.setPen(QPen(QColor("#f7c948"), 2))
            p.drawLine(mx, top - 3, mx, top + h + 3)
            p.setPen(QColor("#9aa0aa"))
            p.drawText(label_w + bar_w + 4, y, value_w, row,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{value}%")


class EmotionDeltas(QWidget):
    """Each emotion relative to the user's resting face: centre = rest, right = more."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rest: dict[str, float] = {}
        self.deltas: dict[str, int] = {e: 0 for e in EMOTION_NAMES}
        self.setMinimumHeight(17 * len(EMOTION_NAMES))

    def set_rest(self, probs: dict[str, float] | None) -> None:
        self.rest = dict(probs or {})

    def set_probs(self, probs: dict[str, float]) -> None:
        self.deltas = {e: int(round((probs.get(e, 0.0) - self.rest.get(e, 0.0)) * 100))
                       for e in EMOTION_NAMES}
        self.update()

    def text_for(self, name: str) -> str:
        d = self.deltas[name]
        if abs(d) < REST_BAND:
            return "≈ rest"
        return f"+{d}" if d > 0 else f"−{-d}"

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        n = len(EMOTION_NAMES)
        row = max(14, self.height() // n)
        label_w, value_w = 80, 48
        bar_w = max(20, self.width() - label_w - value_w - 8)
        mid = label_w + bar_w // 2
        for i, name in enumerate(EMOTION_NAMES):
            y = i * row
            p.setPen(QColor("#c8c8cc"))
            p.drawText(0, y, label_w, row, Qt.AlignmentFlag.AlignVCenter, name.capitalize())
            top = y + row // 2 - 4
            p.fillRect(label_w, top, bar_w, 8, QColor("#30343c"))
            d = max(-100, min(100, self.deltas[name]))
            w = bar_w // 2 * abs(d) // 100
            if abs(d) >= REST_BAND:
                colour = QColor("#1db954" if d > 0 else "#5b8def")
                p.fillRect(mid if d > 0 else mid - w, top, w, 8, colour)
            p.setPen(QPen(QColor("#888888"), 1))
            p.drawLine(mid, top - 2, mid, top + 10)
            p.setPen(QColor("#9aa0aa"))
            p.drawText(label_w + bar_w + 4, y, value_w, row,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       self.text_for(name))
