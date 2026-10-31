"""Application entry point: composition root. Importing this module has no side effects."""
from __future__ import annotations

import logging
import random
import sys
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from moodmusic.config import HOLD_SECONDS, Settings, data_dir, load_settings, save_settings
from moodmusic.logging_setup import setup_logging

log = logging.getLogger(__name__)


class ViewManager:
    """Shows exactly one of the simple widget / advanced dashboard and persists the choice."""
    def __init__(self, settings: Settings, widget, dashboard,
                 save: Callable[[Settings], None] = save_settings) -> None:
        self.settings, self._widget, self._dashboard, self._save = settings, widget, dashboard, save
        widget.switch_view.connect(self.show_view)
        dashboard.switch_view.connect(self.show_view)

    @property
    def current(self) -> str:
        return "advanced" if self.settings.view == "advanced" else "simple"

    def show_view(self, name: str) -> None:
        name = "advanced" if name == "advanced" else "simple"
        self.settings.view = name
        try:
            self._save(self.settings)
        except Exception:
            log.exception("Could not save settings")
        shown, hidden = ((self._dashboard, self._widget) if name == "advanced"
                         else (self._widget, self._dashboard))
        hidden.hide()
        shown.show()
        shown.raise_()
        shown.activateWindow()

    def toggle(self) -> None:
        self.show_view("simple" if self.current == "advanced" else "advanced")


class EngineBridge(QObject):
    """Lives on the main thread so worker signals reach the engine via queued calls (R8)."""
    def __init__(self, engine, worker) -> None:
        super().__init__()
        self._engine = engine
        worker.mood.connect(self.on_mood)
        worker.quality.connect(self.on_quality)
        worker.face_present.connect(self.on_face_present)

    @Slot(object)
    def on_mood(self, state) -> None:
        self._engine.on_mood(state)

    @Slot(object)
    def on_quality(self, report) -> None:
        self._engine.on_quality(report)

    @Slot(bool)
    def on_face_present(self, present: bool) -> None:
        self._engine.on_face_present(present)


class ScanThread(QThread):
    progress = Signal(object)  # ScanProgress
    finished_with = Signal(object)  # final ScanProgress, or None if the scan crashed

    def __init__(self, scanner, playlist_id) -> None:
        super().__init__()
        self._scanner, self._playlist_id, self._stop = scanner, playlist_id, False
        self.result = None

    def stop(self) -> bool:
        """Ask the scan to stop; True once the thread has actually finished."""
        self._stop = True
        return self.wait(3000)

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            result = self._scanner.run(self._playlist_id, self.progress.emit, lambda: self._stop)
        except Exception:
            log.exception("Library scan failed")
            result = None
        self.result = result
        self.finished_with.emit(result)


class ScanController(QObject):
    """Owns scan threads: one at a time, restartable (R15)."""
    progress = Signal(object)
    finished_with = Signal(object)

    def __init__(self, make_scanner: Callable[[], object],
                 get_playlist: Callable[[], str | None]) -> None:
        super().__init__()
        self._make_scanner, self._get_playlist = make_scanner, get_playlist
        self._threads: list[ScanThread] = []
        self._current: ScanThread | None = None
        self._pending = False

    def is_running(self) -> bool:
        return self._current is not None

    def rescan(self) -> None:
        """Start a scan; if one is running, end it early and run exactly one more after it."""
        if self._current is not None:
            self._pending = True
            self._current.request_stop()
            return
        thread = ScanThread(self._make_scanner(), self._get_playlist())
        thread.progress.connect(self.progress)
        thread.finished.connect(self._on_thread_finished)  # QObject slot: runs on the GUI thread
        self._threads = [t for t in self._threads if t.isRunning()] + [thread]
        self._current = thread
        thread.start()

    @Slot()
    def _on_thread_finished(self) -> None:
        thread, self._current = self._current, None
        if thread is not None:
            self.finished_with.emit(thread.result)
        if self._pending:
            self._pending = False
            self.rescan()

    def stop(self) -> bool:
        self._pending = False
        return all([t.stop() for t in self._threads])


def build_scanner(settings: Settings, library, make_spotify_fn=None):
    """A Scanner using the *current* Spotify client id (own service avoids a token-refresh race)."""
    from moodmusic.music.lastfm import LastFmClient
    from moodmusic.music.scanner import Scanner
    from moodmusic.spotify.client import SpotifyService, make_spotify
    sp = (make_spotify_fn or make_spotify)(settings.spotify_client_id)
    return Scanner(SpotifyService(sp), LastFmClient(settings.lastfm_api_key), library)


def report_scan(result, notify: Callable[[str, str], None]) -> None:
    """Surface the outcome of a scan: Scanner's returned error, or a crash (None)."""
    if result is None:
        notify("Mood Music", "Library scan failed. See the log for details.")
    elif result.error:
        notify("Mood Music", result.error)


def _open_dialog(module: str, cls: str, what: str, tray, *args) -> bool:
    """Lazily open a dialog owned by a later task; log if it does not exist yet."""
    try:
        dialog_cls = getattr(__import__(module, fromlist=[cls]), cls)
    except Exception:
        log.exception("%s is not available yet", what)
        if tray is not None:
            tray.message("Mood Music", f"{what} isn't available yet")
        return False
    dialog_cls(*args).exec()
    return True


def _run_wizard(settings: Settings) -> Settings | None:
    """Returns refreshed settings, or None when setup could not complete."""
    try:
        from moodmusic.ui.wizard import SetupWizard
    except Exception:
        log.exception("Setup wizard is not available yet")
        QMessageBox.information(None, "Mood Music", "Setup isn't available yet")
        return None
    SetupWizard(settings).exec()
    settings = load_settings()
    return settings if settings.setup_complete else None


def start_update_check(on_found: Callable[[str], None], current: str | None = None,
                       repo: str | None = None,
                       check: Callable[[str, str], str | None] | None = None):
    """Check for a newer release on a daemon thread; `on_found(url)` runs on the GUI thread.

    Returns the relay object (keep it alive), or None without any thread when no update repo
    is configured.
    """
    import threading

    from moodmusic import __version__
    from moodmusic.app import updates
    from moodmusic.config import UPDATE_REPO
    repo = UPDATE_REPO if repo is None else repo
    if not repo:
        return None
    current = __version__ if current is None else current
    check = check or updates.check_for_update

    class _Relay(QObject):
        found = Signal(str)

    relay = _Relay()
    relay.found.connect(on_found)

    def work() -> None:
        url = check(current, repo)
        if url:
            relay.found.emit(url)

    threading.Thread(target=work, name="update-check", daemon=True).start()
    return relay


def run() -> int:
    from moodmusic.ui.dashboard import Dashboard
    from moodmusic.ui.tray import Tray, make_icon
    from moodmusic.ui.widget import MoodWidget

    setup_logging()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_icon())
    settings = load_settings()
    if not settings.setup_complete:
        settings = _run_wizard(settings)
        if settings is None:
            return 1

    from moodmusic.app.engine import Engine
    from moodmusic.app.worker import VisionWorker
    from moodmusic.mood.calibration import load_baseline
    from moodmusic.mood.corrections import CorrectionStore
    from moodmusic.mood.smoother import MoodSmoother
    from moodmusic.music.library import SongLibrary
    from moodmusic.music.selector import SongSelector
    from moodmusic.spotify.client import SpotifyService, make_spotify
    from moodmusic.vision.camera import CameraSource
    from moodmusic.vision.emotion import HSEmotionModel
    from moodmusic.vision.face import FaceTracker

    service = SpotifyService(make_spotify(settings.spotify_client_id))
    library = SongLibrary(data_dir() / "library.db")
    selector = SongSelector(library, random.Random())
    corrections = CorrectionStore(data_dir() / "corrections.jsonl")
    smoother = MoodSmoother(HOLD_SECONDS.get(settings.sensitivity, HOLD_SECONDS["normal"]))
    baseline = load_baseline()
    worker = VisionWorker(
        camera_factory=lambda: CameraSource(settings.camera_index), tracker_factory=FaceTracker,
        model_factory=HSEmotionModel, baseline=baseline, smoother=smoother,
        corrections=corrections, fps=8)
    engine = Engine(service, selector, settings, time.monotonic, random.Random(),
                    force_mood=worker.force_mood)

    widget, dashboard = MoodWidget(engine, worker), Dashboard(engine, worker)
    views = ViewManager(settings, widget, dashboard)
    bridge = EngineBridge(engine, worker)
    timer = QTimer()

    def quit_app() -> None:
        timer.stop()
        scan_done = scan.stop()
        worker.stop()  # sets the flag and waits up to 2 s, so the camera is released
        if scan_done:
            library.close()
        else:
            log.warning("Scan thread still running; leaving the library open")
        tray.icon.hide()
        app.quit()

    def open_settings() -> None:
        _open_dialog("moodmusic.ui.settings_dialog", "SettingsDialog", "Settings", tray,
                     settings, engine, worker, scan)

    scan = ScanController(
        lambda: build_scanner(settings, library),
        lambda: settings.source_playlist_id)
    scan.finished_with.connect(lambda r: report_scan(r, tray.message))
    tray = Tray(engine, views, open_settings, quit_app)
    dashboard.settings_requested.connect(open_settings)
    dashboard.review_requested.connect(
        lambda: _open_dialog("moodmusic.ui.review_dialog", "ReviewDialog", "Song review",
                             tray, library, scan))
    worker.calibration_done.connect(
        lambda _b: tray.message("Mood Music", "Calibration finished. Thanks!"))
    worker.camera_status.connect(
        lambda s: s != "ok" and tray.message("Mood Music", f"Camera: {s}"))

    def excepthook(exc_type, exc, tb) -> None:
        log.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            tray.message("Mood Music", "Something went wrong. See the log for details.")
        except Exception:
            pass

    sys.excepthook = excepthook

    def tick() -> None:
        engine.tick()
        widget.refresh()

    timer.timeout.connect(tick)
    timer.start(2000)
    tray.show()
    worker.start()
    if baseline is None:
        worker.start_calibration()
        tray.message("Mood Music", "Calibrating: look at the camera for about 20 seconds.")

    update_url: list[str] = []

    def on_update_found(url: str) -> None:
        update_url[:] = [url]
        tray.message("Update available", f"A new Mood Music is out: {url} (click to open)")

    def on_message_clicked() -> None:
        if update_url:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(update_url.pop()))

    tray.icon.messageClicked.connect(on_message_clicked)
    updater = start_update_check(on_update_found)

    scan.rescan()
    views.show_view(settings.view)
    app._moodmusic_refs = (bridge, tray, views, updater)  # keep alive for the event loop
    code = app.exec()
    return code
