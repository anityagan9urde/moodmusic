"""Small pieces shared by the widget and the dashboard."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from moodmusic.config import Settings, save_settings
from moodmusic.mood.intent import Mode

log = logging.getLogger(__name__)

BG = "#1e1e24"
OK, WARN, ERR = QColor("#3ddc84"), QColor("#f5a623"), QColor("#e5484d")
CHOOSE_DEVICE = "Choose a Spotify device"
AUTH_EXPIRED = "Spotify login expired. Please log in again"
CAMERA_MESSAGES = {
    "unavailable": ("error", "Camera unavailable. Check it's connected and not used by another app"),
    "reconnecting": ("warning", "Reconnecting to camera…"),
    "model_failed": ("error", "Mood model failed to load. See the log."),
}

BUTTON_CSS = """
QPushButton { background:#2d2d36; color:#eee; border:none; border-radius:9px; padding:3px 9px;
              font-size:11px; }
QPushButton:hover { background:#3a3a46; }
QPushButton:disabled { color:#777; }
QPushButton:checked { background:#2d6a4f; }
QPushButton#flat { background:transparent; font-size:15px; padding:0 3px; }
"""


def media_icon(kind: str, color: str = "#ffffff", size: int = 32) -> QIcon:
    """Crisp media-control icons ("prev", "next", "play", "pause"); fonts render emoji instead."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    s = size / 32

    def tri(x0, x1):  # pointing right if x1 > x0
        p.drawPolygon(QPolygonF([QPointF(x0 * s, 8 * s), QPointF(x1 * s, 16 * s),
                                 QPointF(x0 * s, 24 * s)]))

    if kind == "play":
        tri(11, 24)
    elif kind == "pause":
        p.drawRoundedRect(int(10 * s), int(8 * s), int(4 * s), int(16 * s), s, s)
        p.drawRoundedRect(int(18 * s), int(8 * s), int(4 * s), int(16 * s), s, s)
    elif kind == "next":
        tri(8, 20)
        p.drawRect(int(20 * s), int(8 * s), int(3 * s), int(16 * s))
    elif kind == "prev":
        tri(24, 12)
        p.drawRect(int(9 * s), int(8 * s), int(3 * s), int(16 * s))
    p.end()
    return QIcon(pm)


def set_play_state(button: QPushButton, playing: bool, color: str = "#ffffff") -> None:
    button.setText("")
    button.setIcon(media_icon("pause" if playing else "play", color))
    button.setToolTip("Pause" if playing else "Play")


def media_button(kind: str, tooltip: str, color: str = "#ffffff") -> QPushButton:
    b = QPushButton()
    b.setIcon(media_icon(kind, color))
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def steady_text(since: float, now: float) -> str:
    minutes = int(max(0.0, now - since) // 60)
    return "just now" if minutes < 1 else f"steady for {minutes} min"


def status_color(kind: str) -> QColor:
    return {"ok": OK, "warning": WARN}.get(kind, ERR)


class StatusDot(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.color = OK

    def set_status(self, kind: str, message: str) -> None:
        self.color = status_color(kind)
        self.setToolTip(message or "All good")
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self.color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 10, 10)


class ArtLabel(QLabel):
    """Album art loaded from a URL; keeps a grey square when there is none."""
    def __init__(self, size: int, parent=None) -> None:
        super().__init__(parent)
        self._size = size
        self._url: str | None = None
        self._net: QNetworkAccessManager | None = None
        self.setFixedSize(size, size)
        self.setStyleSheet("background:#555; border-radius:4px;")

    def set_url(self, url: str | None) -> None:
        if url == self._url:
            return
        self._url = url
        self.clear()
        if not url or not url.startswith("http"):
            return
        if self._net is None:
            self._net = QNetworkAccessManager(self)
        reply = self._net.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda r=reply, u=url: self._loaded(r, u))

    def _loaded(self, reply: QNetworkReply, url: str) -> None:
        try:
            pm = QPixmap()
            if url == self._url and reply.error() == QNetworkReply.NetworkError.NoError:
                if pm.loadFromData(reply.readAll()):
                    self.setPixmap(pm.scaled(QSize(self._size, self._size),
                                             Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                             Qt.TransformationMode.SmoothTransformation))
        finally:
            reply.deleteLater()


class ModeToggle(QWidget):
    """Match / Lift switch; calls engine.set_mode and persists settings.mode."""
    def __init__(self, engine, save: Callable[[Settings], None] = save_settings,
                 parent=None) -> None:
        super().__init__(parent)
        self._engine, self._save = engine, save
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.match_btn, self.lift_btn = QPushButton("Match"), QPushButton("Lift")
        for btn, mode in ((self.match_btn, Mode.MATCH), (self.lift_btn, Mode.LIFT)):
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.clicked.connect(lambda _=False, m=mode: self._choose(m))
            lay.addWidget(btn)
        self.refresh()

    def _choose(self, mode: Mode) -> None:
        self._engine.set_mode(mode)
        self._engine.settings.mode = mode.value
        try:
            self._save(self._engine.settings)
        except Exception:
            log.exception("Could not save settings")

    def refresh(self) -> None:
        lift = self._engine.settings.mode == Mode.LIFT.value
        self.lift_btn.setChecked(lift)
        self.match_btn.setChecked(not lift)


class LoginButton(QPushButton):
    """'Log in to Spotify' button, shown only while the engine says the login expired."""
    def __init__(self, engine, on_click: Callable[[], None], parent=None) -> None:
        super().__init__("Log in to Spotify", parent)
        self._engine = engine
        self.setVisible(False)
        self.clicked.connect(lambda _=False: on_click())

    def refresh(self) -> None:
        self.setVisible(self._engine.status.message == AUTH_EXPIRED)


class DeviceButton(QPushButton):
    """'Choose device...' button, shown only while the engine asks for a device."""
    def __init__(self, engine, parent=None) -> None:
        super().__init__("Choose device…", parent)
        self._engine = engine
        self.setVisible(False)
        self.clicked.connect(self._open_menu)

    def refresh(self) -> None:
        self.setVisible(self._engine.status.message == CHOOSE_DEVICE)

    @staticmethod
    def _popup(menu: QMenu):
        return menu.exec(QCursor.pos())

    def _open_menu(self) -> None:
        menu = QMenu(self)
        for d in self._engine.available_devices():
            action = menu.addAction(f"{d.name} ({d.type})")
            action.setData(d.id)
        if not menu.actions():
            menu.addAction("No devices found").setEnabled(False)
        chosen = self._popup(menu)
        if chosen is not None and chosen.data():
            self._engine.set_device(chosen.data())
