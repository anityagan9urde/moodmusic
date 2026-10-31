"""Settings dialog. Changes apply live on Save (engine shares the settings object)."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout)

from moodmusic.config import HOLD_SECONDS, Settings, data_dir, save_settings
from moodmusic.spotify.auth import KeyringCacheHandler
from moodmusic.ui.async_util import AsyncRunner, load_playlists
from moodmusic.vision.camera import list_cameras

log = logging.getLogger(__name__)

SENSITIVITIES = (("Relaxed", "relaxed"), ("Normal", "normal"), ("Responsive", "responsive"))


def logout_spotify() -> None:
    KeyringCacheHandler().clear()


def open_log_file() -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir() / "moodmusic.log")))


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, engine, worker, scan=None, parent=None, *,
                 playlists_fn: Callable[[], list] | None = None) -> None:
        super().__init__(parent)
        self.settings, self.engine, self.worker, self.scan = settings, engine, worker, scan
        self._playlists_fn = playlists_fn or (lambda: load_playlists(settings.spotify_client_id))
        self._runner = AsyncRunner(self)
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

        self.playlist = QComboBox()
        self.playlist.addItem("Liked Songs", None)
        if settings.source_playlist_id:  # keep the saved choice until the list loads
            self.playlist.addItem("Current playlist", settings.source_playlist_id)
            self.playlist.setCurrentIndex(1)
        form.addRow("Music source", self.playlist)
        self.playlist_status = QLabel("Loading your playlists…")
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self.load_playlists)
        self.retry_button.hide()
        form.addRow(self.playlist_status, self.retry_button)
        self.load_playlists()

        self.recalibrate_button = QPushButton("Recalibrate")
        self.recalibrate_button.clicked.connect(self._recalibrate)
        if hasattr(worker, "calibration_done"):
            worker.calibration_done.connect(self._calibration_done)
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

    def _recalibrate(self) -> None:
        self.recalibrate_button.setEnabled(False)
        self.note.setText("Calibrating — relax and look at the camera…")
        self.worker.start_calibration()

    @Slot(object)
    def _calibration_done(self, _baseline=None) -> None:
        self.recalibrate_button.setEnabled(True)
        self.note.setText("Calibration done.")

    def load_playlists(self) -> None:
        self.retry_button.hide()
        self.playlist_status.setText("Loading your playlists…")
        self._runner.run(self._playlists_fn, self._playlists_loaded)

    def _playlists_loaded(self, playlists, err) -> None:
        if err is not None:
            self.playlist_status.setText("Couldn't load playlists.")
            self.retry_button.show()
            return
        current = self.playlist.currentData()
        self.playlist.clear()
        self.playlist.addItem("Liked Songs", None)
        for pid, name, total in playlists:
            self.playlist.addItem(f"{name} ({total})", pid)
        if current is not None and self.playlist.findData(current) < 0:
            self.playlist.addItem("Current playlist", current)
        self.playlist.setCurrentIndex(max(self.playlist.findData(current), 0))
        self.playlist_status.setText("")

    def done(self, result: int) -> None:
        self._runner.close()
        super().done(result)

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
        new_id_changed = new_id != s.spotify_client_id
        if new_id_changed:
            s.spotify_client_id = new_id
            logout_spotify()  # the old token belongs to the old app
        old_source = s.source_playlist_id
        s.source_playlist_id = self.playlist.currentData()
        save_settings(s)
        if self.scan is not None and (s.source_playlist_id != old_source or new_id_changed):
            self.scan.rescan()
        self.worker.set_hold_seconds(HOLD_SECONDS.get(s.sensitivity, HOLD_SECONDS["normal"]))

    def accept(self) -> None:
        self.save()
        super().accept()
