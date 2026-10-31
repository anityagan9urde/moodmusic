"""Settings dialog. Changes apply live on Save (engine shares the settings object)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout)

from moodmusic.config import HOLD_SECONDS, Settings, data_dir, save_settings
from moodmusic.spotify.auth import KeyringCacheHandler
from moodmusic.vision.camera import list_cameras

log = logging.getLogger(__name__)

SENSITIVITIES = (("Relaxed", "relaxed"), ("Normal", "normal"), ("Responsive", "responsive"))


def logout_spotify() -> None:
    KeyringCacheHandler().clear()


def open_log_file() -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir() / "moodmusic.log")))


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, engine, worker, parent=None) -> None:
        super().__init__(parent)
        self.settings, self.engine, self.worker = settings, engine, worker
        self.setWindowTitle("Mood Music settings")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        self.camera = QComboBox()
        for i in list_cameras() or [settings.camera_index]:
            self.camera.addItem(f"Camera {i}", i)
        self.camera.setCurrentIndex(max(self.camera.findData(settings.camera_index), 0))
        form.addRow("Camera (applies after restart)", self.camera)

        self.sensitivity = QComboBox()
        for label, value in SENSITIVITIES:
            self.sensitivity.addItem(label, value)
        self.sensitivity.setCurrentIndex(max(self.sensitivity.findData(settings.sensitivity), 0))
        form.addRow("Sensitivity", self.sensitivity)

        self.immediate = QCheckBox("Switch songs immediately (otherwise wait for the song to end)")
        self.immediate.setChecked(settings.switch_mode == "immediate")
        form.addRow(self.immediate)

        self.away = QSpinBox()
        self.away.setRange(0, 120)
        self.away.setSuffix(" min (0 = off)")
        self.away.setValue(settings.away_pause_minutes)
        form.addRow("Pause music when I'm away", self.away)

        self.start_login = QCheckBox("Start at login (saved only; not wired to the OS yet)")
        self.start_login.setChecked(settings.start_at_login)
        form.addRow(self.start_login)

        self.client_id = QLineEdit(settings.spotify_client_id)
        form.addRow("Spotify Client ID", self.client_id)

        self.playlist = QLineEdit(settings.source_playlist_id or "")
        self.playlist.setPlaceholderText("Empty = Liked Songs")
        form.addRow("Playlist ID", self.playlist)
        form.addRow(QLabel("Playlist and Client ID changes take effect on next launch "
                           "(the library is rescanned then)."))

        self.recalibrate_button = QPushButton("Recalibrate")
        self.recalibrate_button.clicked.connect(lambda: self.worker.start_calibration())
        self.logout_button = QPushButton("Log out of Spotify")
        self.logout_button.clicked.connect(self._logout)
        self.log_button = QPushButton("Open log file")
        self.log_button.clicked.connect(open_log_file)
        for b in (self.recalibrate_button, self.logout_button, self.log_button):
            lay.addWidget(b)
        self.note = QLabel("")
        lay.addWidget(self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _logout(self) -> None:
        logout_spotify()
        self.note.setText("Logged out. You'll be asked to log in again next launch.")

    def save(self) -> None:
        s = self.settings
        s.camera_index = self.camera.currentData() or 0
        s.sensitivity = self.sensitivity.currentData()
        s.switch_mode = "immediate" if self.immediate.isChecked() else "wait"
        s.away_pause_minutes = self.away.value()
        s.start_at_login = self.start_login.isChecked()
        new_id = self.client_id.text().strip()
        if new_id != s.spotify_client_id:
            s.spotify_client_id = new_id
            logout_spotify()  # the old token belongs to the old app
        s.source_playlist_id = self.playlist.text().strip() or None
        save_settings(s)
        self.worker.set_hold_seconds(HOLD_SECONDS.get(s.sensitivity, HOLD_SECONDS["normal"]))

    def accept(self) -> None:
        self.save()
        super().accept()
