"""Pages of the first-run wizard."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QProgressBar, QPushButton, QVBoxLayout, QWizardPage)

from moodmusic.spotify.auth import REDIRECT_URI
from moodmusic.spotify.client import NotPremium, SpotifyError

log = logging.getLogger(__name__)

NOT_PREMIUM_TEXT = "Spotify Premium is needed to control playback"
WAITING_TEXT = "Waiting for you to approve in the browser…"


class FuncThread(QThread):
    """Runs fn() off the GUI thread; emits (result, error)."""
    finished_with = Signal(object, object)

    def __init__(self, fn: Callable, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished_with.emit(self._fn(), None)
        except Exception as e:  # reported to the page, never raised across threads
            self.finished_with.emit(None, e)


def _label(text: str, rich: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    if rich:
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setOpenExternalLinks(True)
    return lab


class _AsyncPage(QWizardPage):
    def _run(self, fn: Callable, done: Callable[[object, object], None]) -> None:
        self._thread = FuncThread(fn, self)
        self._thread.finished_with.connect(done)
        self._thread.start()


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Welcome to Mood Music")
        lay = QVBoxLayout(self)
        lay.addWidget(_label(
            "Mood Music reads your mood from your webcam and plays matching songs from your "
            "own Spotify library.\n\nYour video never leaves this computer and nothing is "
            "recorded or stored. Only a few numbers describing your expression are used, and "
            "only while the app runs."))


class SpotifyPage(_AsyncPage):
    def __init__(self, settings, login_fn: Callable[[str], None], on_next: Callable[[], int]) -> None:
        super().__init__()
        self._settings, self._login_fn, self._on_next = settings, login_fn, on_next
        self._ok = False
        self.setTitle("Connect Spotify")
        lay = QVBoxLayout(self)
        lay.addWidget(_label(
            "1. Open <a href='https://developer.spotify.com/dashboard'>"
            "developer.spotify.com/dashboard</a> and choose Create app.<br>"
            f"2. Set the redirect URI to <b>{REDIRECT_URI}</b><br>"
            "3. Tick <b>Web API</b>, then save.<br>"
            "4. Paste the app's Client ID below.", rich=True))
        row = QHBoxLayout()
        row.addWidget(QLabel("Redirect URI:"))
        uri = QLineEdit(REDIRECT_URI)
        uri.setReadOnly(True)
        row.addWidget(uri)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(REDIRECT_URI))
        row.addWidget(self.copy_button)
        lay.addLayout(row)
        self.client_edit = QLineEdit(settings.spotify_client_id)
        self.client_edit.setPlaceholderText("Client ID")
        self.client_edit.textChanged.connect(self._reset)
        lay.addWidget(self.client_edit)
        self.login_button = QPushButton("Log in to Spotify")
        self.login_button.clicked.connect(self.start_login)
        lay.addWidget(self.login_button)
        self.status = _label("")
        lay.addWidget(self.status)

    def _reset(self) -> None:
        self._ok = False
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self._ok

    def nextId(self) -> int:  # noqa: N802
        return self._on_next()

    def start_login(self) -> None:
        cid = self.client_edit.text().strip()
        if not cid:
            self.status.setText("Paste your Client ID first.")
            return
        self.login_button.setEnabled(False)
        self.status.setText(WAITING_TEXT)
        self._run(lambda: self._login_fn(cid), lambda _r, err: self._finished(cid, err))

    def _finished(self, cid: str, err: Exception | None) -> None:
        self.login_button.setEnabled(True)
        if err is None:
            self._settings.spotify_client_id = cid
            self._ok = True
            self.status.setText("Logged in. Click Next.")
        elif isinstance(err, NotPremium):
            self.status.setText(NOT_PREMIUM_TEXT)
        elif isinstance(err, SpotifyError):
            self.status.setText(f"{err}. You can try again.")
        else:
            log.warning("Spotify login failed: %s", type(err).__name__)
            self.status.setText("Login failed. You can try again.")
        self.completeChanged.emit()


class LastFmPage(_AsyncPage):
    def __init__(self, settings, validate_fn: Callable[[str], None]) -> None:
        super().__init__()
        self._settings, self._validate_fn, self._ok = settings, validate_fn, False
        self.setTitle("Connect Last.fm")
        lay = QVBoxLayout(self)
        lay.addWidget(_label(
            "Last.fm tells the app what each song sounds like. Create a free API account at "
            "<a href='https://www.last.fm/api/account/create'>"
            "https://www.last.fm/api/account/create</a> and paste the API key here.", rich=True))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("API key")
        self.key_edit.textChanged.connect(self._reset)
        lay.addWidget(self.key_edit)
        self.check_button = QPushButton("Check key")
        self.check_button.clicked.connect(self.start_validate)
        lay.addWidget(self.check_button)
        self.status = _label("")
        lay.addWidget(self.status)

    def _reset(self) -> None:
        self._ok = False
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self._ok

    def start_validate(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            self.status.setText("Paste your API key first.")
            return
        self.check_button.setEnabled(False)
        self.status.setText("Checking…")
        self._run(lambda: self._validate_fn(key), lambda _r, err: self._finished(key, err))

    def _finished(self, key: str, err: Exception | None) -> None:
        self.check_button.setEnabled(True)
        if err is None:
            self._settings.lastfm_api_key = key
            self._ok = True
            self.status.setText("Key works. Click Next.")
        else:
            self.status.setText(str(err) or "Could not check the key. Try again.")
        self.completeChanged.emit()


class CameraPage(QWizardPage):
    def __init__(self, wizard, cameras_fn: Callable[[], list[int]]) -> None:
        super().__init__()
        self._wiz, self._cameras_fn, self._ok = wizard, cameras_fn, False
        self.setTitle("Camera")
        lay = QVBoxLayout(self)
        self.camera_combo = QComboBox()
        lay.addWidget(self.camera_combo)
        self.preview_label = QLabel("Camera preview")
        self.preview_label.setFixedSize(320, 240)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background:#333; color:#aaa; border-radius:6px;")
        lay.addWidget(self.preview_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.quality_label = _label("Looking for your face…")
        lay.addWidget(self.quality_label)
        self._loaded = False

    def initializePage(self) -> None:  # noqa: N802
        if not self._loaded:
            self._loaded = True
            cams = self._cameras_fn() or [0]
            for i in cams:
                self.camera_combo.addItem(f"Camera {i}", i)
            idx = self.camera_combo.findData(self._wiz.settings.camera_index)
            self.camera_combo.setCurrentIndex(max(idx, 0))
            self.camera_combo.currentIndexChanged.connect(self._camera_changed)
        self._wiz.settings.camera_index = self.camera_combo.currentData() or 0
        self._restart()

    def _restart(self) -> None:
        self._ok = False
        self.quality_label.setText("Looking for your face…")
        self._wiz.restart_worker(self._wiz.settings.camera_index)
        self.completeChanged.emit()

    def _camera_changed(self) -> None:
        self._wiz.settings.camera_index = self.camera_combo.currentData() or 0
        self._restart()

    def isComplete(self) -> bool:  # noqa: N802
        return self._ok

    def on_quality(self, report) -> None:
        self._ok = bool(report.ok)
        self.quality_label.setText("Looks good. Click Next." if report.ok
                                   else (report.issue or "Can't see your face clearly."))
        self.completeChanged.emit()

    def on_preview(self, image) -> None:
        self.preview_label.setPixmap(QPixmap.fromImage(image).scaled(
            self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))


class CalibrationPage(QWizardPage):
    def __init__(self, wizard) -> None:
        super().__init__()
        self._wiz, self._done = wizard, False
        self.setTitle("Calibration")
        lay = QVBoxLayout(self)
        lay.addWidget(_label("Relax and look at the screen for about 20 seconds so the app "
                             "learns what your neutral face looks like."))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        lay.addWidget(self.progress)

    def initializePage(self) -> None:  # noqa: N802
        self._done = False
        self.progress.setValue(0)
        worker = self._wiz.worker
        if worker is not None:
            worker.set_preview(False)
            worker.start_calibration()

    def isComplete(self) -> bool:  # noqa: N802
        return self._done

    def on_progress(self, fraction: float) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 100))

    def on_done(self, _baseline) -> None:
        self._done = True
        self.progress.setValue(100)
        self.completeChanged.emit()


class SourcePage(_AsyncPage):
    def __init__(self, settings, playlists_fn: Callable[[], list]) -> None:
        super().__init__()
        self._settings, self._playlists_fn = settings, playlists_fn
        self.setTitle("Choose your music")
        lay = QVBoxLayout(self)
        lay.addWidget(_label("Pick where songs should come from."))
        self.list = QListWidget()
        lay.addWidget(self.list)
        self.status = _label("")
        lay.addWidget(self.status)
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self.load)
        self.retry_button.hide()
        lay.addWidget(self.retry_button)

    def initializePage(self) -> None:  # noqa: N802
        self.load()

    def load(self) -> None:
        self.retry_button.hide()
        self.status.setText("Loading your playlists…")
        self._run(self._playlists_fn, self._loaded)

    def _loaded(self, playlists, err) -> None:
        self.list.clear()
        if err is not None:
            self.status.setText("Couldn't load your playlists. Check your connection and retry.")
            self.retry_button.show()
            return
        self.status.setText("")
        self.list.addItem("Liked Songs")
        self.list.item(0).setData(Qt.ItemDataRole.UserRole, None)
        for pid, name, total in playlists:
            self.list.addItem(f"{name} ({total})")
            self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, pid)
        self.list.setCurrentRow(0)

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None
