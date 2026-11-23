"""Pages of the first-run wizard."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QProgressBar, QPushButton, QVBoxLayout, QWizardPage)

from moodmusic.ui.async_util import AsyncRunner
from moodmusic.spotify.auth import REDIRECT_URI
from moodmusic.spotify.client import NotPremium, SpotifyError
from moodmusic.ui.login import WAITING_TEXT, login_error_text

log = logging.getLogger(__name__)

NOT_PREMIUM_TEXT = "Spotify Premium is needed to control playback"


def _label(text: str, rich: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    if rich:
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setOpenExternalLinks(True)
    return lab


class _AsyncPage(QWizardPage):
    def _run(self, fn: Callable, done: Callable[[object, object], None]) -> None:
        if not hasattr(self, "_runner"):
            self._runner = AsyncRunner(self)
        self._runner.run(fn, done)

    def shutdown(self) -> None:
        if hasattr(self, "_runner"):
            self._runner.close()


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
    def __init__(self, settings, login_fn: Callable[..., None],
                 on_next: Callable[[], int]) -> None:
        """login_fn(client_id, cancel=threading.Event) blocks until login ends (thread)."""
        super().__init__()
        self._settings, self._login_fn, self._on_next = settings, login_fn, on_next
        self._ok = False
        self._cancel: threading.Event | None = None
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
        self.cancel_button = QPushButton("Cancel login")
        self.cancel_button.clicked.connect(self.cancel_login)
        self.cancel_button.hide()
        lay.addWidget(self.cancel_button)
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
        self.cancel_button.show()
        self.status.setText(WAITING_TEXT)
        cancel = self._cancel = threading.Event()
        login_fn = self._login_fn
        self._run(lambda: login_fn(cid, cancel=cancel), lambda _r, err: self._finished(cid, err))

    def cancel_login(self) -> None:
        """Abandon a waiting login; the thread frees port 8765 within half a second."""
        if self._cancel is not None:
            self._cancel.set()

    def shutdown(self) -> None:
        self.cancel_login()
        super().shutdown()

    def _finished(self, cid: str, err: Exception | None) -> None:
        self._cancel = None
        self.login_button.setEnabled(True)
        self.cancel_button.hide()
        if err is None:
            self._settings.spotify_client_id = cid
            self._ok = True
            self.status.setText("Logged in. Click Next.")
        elif isinstance(err, NotPremium):
            self.status.setText(NOT_PREMIUM_TEXT)
        elif isinstance(err, SpotifyError):
            self.status.setText(f"{err}. You can try again.")
        else:
            self.status.setText(login_error_text(err) or "Login cancelled.")
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
