"""Explicit "Log in to Spotify" action: runs the browser login off the GUI thread."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from moodmusic.spotify.auth import (LoginCancelled, LoginError, LoginInProgress, LoginTimeout,
                                    login_interactive)
from moodmusic.ui.async_util import AsyncRunner

log = logging.getLogger(__name__)

WAITING_TEXT = "Waiting for you to approve in the browser…"
TIMEOUT_TEXT = ("Didn't hear back from Spotify. Check the redirect URI in your Spotify app "
                "settings, then try again.")
FAILED_TEXT = "Spotify login failed. You can try again."


def login_error_text(err: Exception) -> str | None:
    """User-facing text for a failed interactive login (None when the user cancelled)."""
    if isinstance(err, LoginCancelled):
        return None
    if isinstance(err, LoginTimeout):
        return TIMEOUT_TEXT
    if isinstance(err, (LoginInProgress, LoginError)):
        return str(err)
    log.warning("Spotify login failed: %s", type(err).__name__)  # never the message (tokens)
    return FAILED_TEXT


class LoginWaitDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log in to Spotify")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(WAITING_TEXT))
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        lay.addWidget(self.cancel_button)


class LoginController(QObject):
    """One interactive login at a time; Cancel or closing the dialog abandons it safely."""

    def __init__(self, get_client_id: Callable[[], str], on_success: Callable[[], None],
                 notify: Callable[[str, str], None],
                 login_fn: Callable[..., None] = login_interactive, parent=None) -> None:
        super().__init__(parent)
        self._get_client_id, self._on_success, self._notify = get_client_id, on_success, notify
        self._login_fn = login_fn
        self._cancel: threading.Event | None = None
        self._runner: AsyncRunner | None = None
        self.dialog: LoginWaitDialog | None = None

    def is_running(self) -> bool:
        return self._cancel is not None

    def start(self) -> None:
        if self.is_running():
            self.dialog.show()
            self.dialog.raise_()
            return
        cid = self._get_client_id().strip()
        if not cid:
            self._notify("Mood Music", "Add your Spotify Client ID in Settings first.")
            return
        cancel = self._cancel = threading.Event()
        self._runner = AsyncRunner(self)
        self.dialog = LoginWaitDialog()
        self.dialog.rejected.connect(self.cancel)
        self.dialog.show()
        login_fn = self._login_fn
        self._runner.run(lambda: login_fn(cid, cancel=cancel), self._done)

    def cancel(self) -> None:
        """Abandon a running login: the thread notices within half a second and exits."""
        if self._cancel is not None:
            self._cancel.set()
        self._finish()

    shutdown = cancel

    def _finish(self) -> None:
        self._cancel = None
        if self._runner is not None:
            self._runner.close()  # a late result is ignored
            self._runner = None
        if self.dialog is not None:
            dialog, self.dialog = self.dialog, None
            dialog.rejected.disconnect(self.cancel)
            dialog.close()
            dialog.deleteLater()

    def _done(self, _result, err) -> None:
        self._finish()
        if err is None:
            try:
                self._on_success()
            finally:
                self._notify("Mood Music", "Logged in to Spotify.")
            return
        text = login_error_text(err)
        if text:
            self._notify("Mood Music", text)
