"""System tray icon and menu."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon() -> QIcon:
    """Generated icon (filled circle); no binary assets."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#f7c948"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.end()
    return QIcon(pm)


class Tray:
    def __init__(self, engine, views, on_settings, on_quit, on_login=None) -> None:
        self.icon = QSystemTrayIcon(make_icon())
        self.icon.setToolTip("Mood Music")
        self.menu = QMenu()
        self.show_action = self.menu.addAction("Show")
        self.pause_action = QAction("Pause auto-pick", self.menu)
        self.pause_action.setCheckable(True)
        self.menu.addAction(self.pause_action)
        self.toggle_view_action = self.menu.addAction("")
        self.settings_action = self.menu.addAction("Settings")
        self.login_action = self.menu.addAction("Log in to Spotify")
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("Quit")
        self.icon.setContextMenu(self.menu)

        self._views = views
        self.show_action.triggered.connect(lambda: views.show_view(views.current))
        self.pause_action.toggled.connect(lambda paused: engine.set_enabled(not paused))
        self.toggle_view_action.triggered.connect(views.toggle)
        self.settings_action.triggered.connect(on_settings)
        if on_login is not None:
            self.login_action.triggered.connect(on_login)
        else:
            self.login_action.setVisible(False)
        self.quit_action.triggered.connect(on_quit)
        self.icon.activated.connect(self._activated)
        self.menu.aboutToShow.connect(self.update_view_label)
        self.update_view_label()

    def update_view_label(self) -> None:
        self.toggle_view_action.setText(
            "Simple view" if self._views.current == "advanced" else "Advanced view")

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._views.show_view(self._views.current)

    def show(self) -> None:
        self.icon.show()

    def message(self, title: str, text: str) -> None:
        self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)
