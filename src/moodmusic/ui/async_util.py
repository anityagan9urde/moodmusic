"""Run a blocking call off the GUI thread without tying the thread to a widget's lifetime."""
from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

# Running threads are kept here so closing a dialog never destroys a live QThread
# (a PKCE login can sit waiting on the browser for minutes).
_LIVE: set[QThread] = set()


class FuncThread(QThread):
    finished_with = Signal(int, object, object)  # generation, result, error

    def __init__(self, fn: Callable, generation: int) -> None:
        super().__init__()
        self._fn, self._gen = fn, generation

    def run(self) -> None:
        try:
            self.finished_with.emit(self._gen, self._fn(), None)
        except Exception as e:  # handed to the GUI thread, never raised across threads
            self.finished_with.emit(self._gen, None, e)


def _reap(thread: QThread) -> None:
    _LIVE.discard(thread)
    thread.deleteLater()


class AsyncRunner(QObject):
    """run(fn, cb): cb(result, error) is called on the GUI thread, only for the latest run
    and only while the runner is open (stale or post-close results are dropped)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._gen, self._cb, self._closed = 0, None, False

    def run(self, fn: Callable, cb: Callable[[object, object], None]) -> None:
        self._gen += 1
        self._cb = cb
        thread = FuncThread(fn, self._gen)
        thread.finished_with.connect(self._on_result)  # bound QObject slot: queued to GUI thread
        thread.finished.connect(lambda t=thread: _reap(t))
        _LIVE.add(thread)
        thread.start()

    def close(self) -> None:
        self._closed = True
        self._gen += 1

    @Slot(int, object, object)
    def _on_result(self, gen: int, result, err) -> None:
        if self._closed or gen != self._gen or self._cb is None:
            return
        self._cb(result, err)


def wait_live(timeout_ms: int) -> bool:
    """Wait up to timeout_ms in total for running helper threads; True if none are left."""
    deadline = time.monotonic() + timeout_ms / 1000
    for thread in list(_LIVE):
        remaining = int(max(0.0, deadline - time.monotonic()) * 1000)
        if not thread.wait(remaining) and thread.isRunning():
            return False
    return all(not t.isRunning() for t in list(_LIVE))


def load_playlists(client_id: str) -> list:
    """Blocking: the user's playlists as (id, name, total). Call from a thread."""
    from moodmusic.spotify.client import SpotifyService, make_spotify
    return SpotifyService(make_spotify(client_id)).playlists()
