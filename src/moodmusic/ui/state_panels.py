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
