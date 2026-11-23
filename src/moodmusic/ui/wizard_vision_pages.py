"""Camera, calibration and music-source pages of the first-run wizard."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QLabel, QListWidget, QProgressBar, QPushButton,
                               QVBoxLayout, QWizardPage)

from moodmusic.ui.wizard_pages import _AsyncPage, _label


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

    def on_status(self, status: str) -> None:
        if status == "unavailable":
            self._ok = False
            self.quality_label.setText("Camera unavailable. Check it's connected and that "
                                       "Windows/macOS allows camera access.")
            self.completeChanged.emit()
        elif status == "reconnecting":
            self._ok = False
            self.quality_label.setText("Reconnecting to camera…")
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
        self.list.currentRowChanged.connect(lambda _r: self.completeChanged.emit())
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
        self.list.addItem("Liked Songs")
        self.list.item(0).setData(Qt.ItemDataRole.UserRole, None)
        if err is not None:
            self.status.setText("Couldn't load your playlists, so only Liked Songs is "
                                "available. Retry to see your playlists.")
            self.retry_button.show()
        else:
            self.status.setText("")
            for pid, name, total in playlists:
                self.list.addItem(f"{name} ({total})")
                self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, pid)
        self.list.setCurrentRow(0)
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self.list.currentItem() is not None

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None
