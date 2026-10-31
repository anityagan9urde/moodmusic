"""First-run setup wizard."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QWizard

from moodmusic.config import HOLD_SECONDS, Settings, data_dir, save_settings
from moodmusic.ui.async_util import load_playlists
from moodmusic.ui.wizard_pages import LastFmPage, SpotifyPage, WelcomePage
from moodmusic.ui.wizard_vision_pages import CalibrationPage, CameraPage, SourcePage

log = logging.getLogger(__name__)

PAGE_WELCOME, PAGE_SPOTIFY, PAGE_LASTFM, PAGE_CAMERA, PAGE_CALIBRATION, PAGE_SOURCE = range(6)


def bundled_lastfm_key() -> str | None:
    """Key shipped in resources/lastfm_key.txt (works unpacked and in a PyInstaller bundle)."""
    from moodmusic.resources import resource_path
    path = resource_path("lastfm_key.txt")
    if path is None:
        return None
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None


def _default_login(client_id: str) -> None:
    from moodmusic.spotify.client import SpotifyService, make_spotify
    SpotifyService(make_spotify(client_id)).check_premium()


def _default_validate(key: str) -> None:
    from moodmusic.music.lastfm import LastFmClient
    LastFmClient(key).artist_tags("Radiohead")


def _default_worker(index: int):
    from moodmusic.app.worker import VisionWorker
    from moodmusic.mood.corrections import CorrectionStore
    from moodmusic.mood.smoother import MoodSmoother
    from moodmusic.vision.camera import CameraSource
    from moodmusic.vision.emotion import HSEmotionModel
    from moodmusic.vision.face import FaceTracker
    return VisionWorker(
        camera_factory=lambda: CameraSource(index), tracker_factory=FaceTracker,
        model_factory=HSEmotionModel, baseline=None,
        smoother=MoodSmoother(HOLD_SECONDS["normal"]),
        corrections=CorrectionStore(data_dir() / "corrections.jsonl"), fps=8)


class SetupWizard(QWizard):
    """Seams (login_fn, validate_fn, worker_factory, cameras_fn, playlists_fn) keep tests offline."""

    def __init__(self, settings: Settings, parent=None, *, login_fn: Callable | None = None,
                 validate_fn: Callable | None = None, worker_factory: Callable | None = None,
                 cameras_fn: Callable | None = None, playlists_fn: Callable | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.worker = None
        self._worker_factory = worker_factory or _default_worker
        self.setWindowTitle("Mood Music setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        key = bundled_lastfm_key()
        self.lastfm_skipped = key is not None
        if key:
            settings.lastfm_api_key = key

        def default_playlists() -> list:
            return load_playlists(settings.spotify_client_id)

        if cameras_fn is None:
            from moodmusic.vision.camera import list_cameras
            cameras_fn = list_cameras
        self._camera = CameraPage(self, cameras_fn)
        self._calibration = CalibrationPage(self)
        self.setPage(PAGE_WELCOME, WelcomePage())
        self.setPage(PAGE_SPOTIFY, SpotifyPage(
            settings, login_fn or _default_login,
            lambda: PAGE_CAMERA if self.lastfm_skipped else PAGE_LASTFM))
        self.setPage(PAGE_LASTFM, LastFmPage(settings, validate_fn or _default_validate))
        self.setPage(PAGE_CAMERA, self._camera)
        self.setPage(PAGE_CALIBRATION, self._calibration)
        self.setPage(PAGE_SOURCE, SourcePage(settings, playlists_fn or default_playlists))

    def restart_worker(self, index: int) -> None:
        self.stop_worker()
        worker = self._worker_factory(index)
        worker.preview.connect(self._camera.on_preview)
        worker.quality.connect(self._camera.on_quality)
        worker.camera_status.connect(self._camera.on_status)
        worker.calibration_progress.connect(self._calibration.on_progress)
        worker.calibration_done.connect(self._calibration.on_done)
        worker.set_preview(True)
        worker.start()
        self.worker = worker

    def stop_worker(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None

    def accept(self) -> None:
        source = self.page(PAGE_SOURCE)
        if not source.isComplete():
            return  # no valid selection yet
        self.settings.source_playlist_id = source.selected_id()
        self.settings.setup_complete = True
        save_settings(self.settings)
        super().accept()

    def done(self, result: int) -> None:
        for pid in (PAGE_SPOTIFY, PAGE_LASTFM, PAGE_SOURCE):
            self.page(pid).shutdown()  # late results from running threads are ignored
        self.stop_worker()
        super().done(result)
