"""Settings: grouped, in plain words, applied the moment you change them."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from moodmusic.autostart import set_start_at_login
from moodmusic.config import HOLD_SECONDS, Settings, data_dir, save_settings
from moodmusic.mood.groups import MoodGroup
from moodmusic.mood.intent import Mode
from moodmusic.spotify.auth import KeyringCacheHandler
from moodmusic.ui.async_util import AsyncRunner, load_playlists
from moodmusic.ui.common import AUTH_EXPIRED
from moodmusic.vision.camera import list_cameras

log = logging.getLogger(__name__)

REACT_CHOICES = (
    (f"Quick · {HOLD_SECONDS['responsive']} s", "responsive"),
    (f"Balanced · {HOLD_SECONDS['normal']} s", "normal"),
    (f"Steady · {HOLD_SECONDS['relaxed']} s", "relaxed"),
)
SWITCH_CHOICES = (("Switch now", "immediate"), ("Finish song", "wait"))
STYLE_CHOICES = (("Match", Mode.MATCH.value), ("Lift", Mode.LIFT.value))
AWAY_CHOICES = (("Never", 0), ("5 min", 5), ("10 min", 10), ("15 min", 15), ("30 min", 30),
                ("1 hour", 60))

CSS = """
QDialog, QWidget#page { background:#1b1d22; color:#e8e8ea; font-size:12px; }
QLabel#section { color:#9aa0aa; font-size:10px; font-weight:600; letter-spacing:1px;
                 padding-top:6px; }
QFrame#item { background:#24272e; border-radius:8px; }
QFrame#item QLabel { background:transparent; }
QLabel#hint { color:#9aa0aa; font-size:11px; }
QPushButton { background:#30343c; color:#eee; border:none; border-radius:6px; padding:5px 12px; }
QPushButton:hover { background:#3a3f49; }
QPushButton:disabled { color:#777; }
QPushButton#seg { background:transparent; border-radius:5px; padding:4px 10px; }
QPushButton#seg:checked { background:#1db954; color:#000; font-weight:600; }
QWidget#segbox { background:#30343c; border-radius:7px; }
QPushButton#done { background:#1db954; color:#000; font-weight:600; padding:6px 18px; }
QPushButton#fold { background:transparent; color:#9aa0aa; text-align:left; padding:4px 2px; }
QComboBox, QLineEdit { background:#30343c; border:none; border-radius:6px; padding:4px 8px;
                       color:#eee; }
QCheckBox::indicator { width:34px; height:18px; border-radius:9px; background:#444; }
QCheckBox::indicator:checked { background:#1db954; }
"""


def logout_spotify() -> None:
    KeyringCacheHandler().clear()


def open_log_file() -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir() / "moodmusic.log")))


class Segmented(QWidget):
    """Side-by-side choice buttons (exactly one selected)."""
    changed = Signal(str)

    def __init__(self, choices, value: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("segbox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        self.buttons: dict[str, QPushButton] = {}
        for label, data in choices:
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, d=data: self.select(d))
            self.buttons[data] = b
            lay.addWidget(b)
        if value in self.buttons:
            self.buttons[value].setChecked(True)

    def value(self) -> str | None:
        return next((d for d, b in self.buttons.items() if b.isChecked()), None)

    def select(self, data: str) -> None:
        self.buttons[data].setChecked(True)
        self.changed.emit(data)


def _item(title: str, hint: str, control: QWidget | None) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("item")
    lay = QHBoxLayout(frame)
    lay.setContentsMargins(12, 8, 12, 8)
    texts = QVBoxLayout()
    texts.setSpacing(1)
    texts.addWidget(QLabel(title))
    hint_label = QLabel(hint)
    hint_label.setObjectName("hint")
    hint_label.setWordWrap(True)
    hint_label.setVisible(bool(hint))
    texts.addWidget(hint_label)
    lay.addLayout(texts, 1)
    if control is not None:
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return frame, hint_label


def _section(title: str) -> QLabel:
    label = QLabel(title.upper())
    label.setObjectName("section")
    return label


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, engine, worker, scan=None, parent=None, *,
                 playlists_fn: Callable[[], list] | None = None,
                 cameras_fn: Callable[[], list[int]] | None = None,
                 on_spotify_changed: Callable[[], None] | None = None,
                 autostart_fn: Callable[[bool], bool] = set_start_at_login) -> None:
        super().__init__(parent)
        self.settings, self.engine, self.worker, self.scan = settings, engine, worker, scan
        self._playlists_fn = playlists_fn or (lambda: load_playlists(settings.spotify_client_id))
        self._on_spotify_changed = on_spotify_changed
        self._autostart = autostart_fn
        self._loading = True  # filling controls must not count as user changes
        self._runner = AsyncRunner(self)
        self._camera_runner = AsyncRunner(self)
        self.setWindowTitle("Mood Music settings")
        self.setStyleSheet(CSS)
        self.resize(540, 680)

        page = QWidget()
        page.setObjectName("page")
        body = QVBoxLayout(page)
        body.setSpacing(6)
        s = settings

        # -- Music ------------------------------------------------------------------
        body.addWidget(_section("Music"))
        self.playlist = QComboBox()
        self.playlist.addItem("Liked Songs", None)
        if s.source_playlist_id:  # keep the saved choice until the list loads
            self.playlist.addItem("Current playlist", s.source_playlist_id)
            self.playlist.setCurrentIndex(1)
        self.playlist.currentIndexChanged.connect(lambda _i: self._source_changed())
        frame, self.source_hint = _item("Play from", self._song_count_text(), self.playlist)
        body.addWidget(frame)
        status_row = QHBoxLayout()
        self.playlist_status = QLabel("Loading your playlists…")
        self.playlist_status.setObjectName("hint")
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self.load_playlists)
        self.retry_button.hide()
        status_row.addWidget(self.playlist_status, 1)
        status_row.addWidget(self.retry_button)
        body.addLayout(status_row)

        self.switch = Segmented(SWITCH_CHOICES, s.switch_mode)
        self.switch.changed.connect(lambda _v: self.save())
        body.addWidget(_item("When your mood changes",
                             "Switch the song now, or let the current one finish first",
                             self.switch)[0])
        self.music_style = Segmented(STYLE_CHOICES, s.mode)
        self.music_style.changed.connect(self._style_changed)
        body.addWidget(_item("Music style", "Match how you feel, or gently lift you up",
                             self.music_style)[0])

        # -- Face reading -------------------------------------------------------------
        body.addWidget(_section("Face reading"))
        self.react = Segmented(REACT_CHOICES, s.sensitivity)
        self.react.changed.connect(lambda _v: self.save())
        body.addWidget(_item("How quickly it reacts",
                             "A new state has to last this long before the music changes",
                             self.react)[0])
        self.camera = QComboBox()
        self._set_cameras([])  # the saved camera right away; probing runs off the GUI thread
        self._camera_runner.run(cameras_fn or (lambda: list_cameras()),
                                lambda cams, err: self._set_cameras(cams if err is None else []))
        self.camera.currentIndexChanged.connect(lambda _i: self.save())
        body.addWidget(_item("Camera", "Takes effect after you restart Mood Music",
                             self.camera)[0])
        self.recalibrate_button = QPushButton("Start")
        self.recalibrate_button.clicked.connect(self._recalibrate)
        if hasattr(worker, "calibration_done"):
            worker.calibration_done.connect(self._calibration_done)
        body.addWidget(_item("Recalibrate",
                             "Sit normally and look at the screen for 20 s. Do this if it "
                             "misreads your resting face.", self.recalibrate_button)[0])
        self.note = QLabel("")
        self.note.setObjectName("hint")
        body.addWidget(self.note)

        # -- Stepping away -------------------------------------------------------------
        body.addWidget(_section("When you step away"))
        self.away = QComboBox()
        for label, minutes in AWAY_CHOICES:
            self.away.addItem(label, minutes)
        if self.away.findData(s.away_pause_minutes) < 0:
            self.away.addItem(f"{s.away_pause_minutes} min", s.away_pause_minutes)
        self.away.setCurrentIndex(self.away.findData(s.away_pause_minutes))
        self.away.currentIndexChanged.connect(lambda _i: self.save())
        body.addWidget(_item("Pause music when you're away for",
                             "No face seen for this long", self.away)[0])
        self.start_login = QCheckBox()
        self.start_login.setChecked(s.start_at_login)
        self.start_login.toggled.connect(self._start_login_changed)
        frame, self.login_hint = _item("Start Mood Music when I log in", "", self.start_login)
        body.addWidget(frame)

        # -- Spotify ---------------------------------------------------------------------
        body.addWidget(_section("Spotify"))
        self.logout_button = QPushButton("Log out")
        self.logout_button.clicked.connect(self._logout)
        frame, _ = _item("Account", "", self.logout_button)
        self.spotify_status = frame.findChildren(QLabel)[0]
        body.addWidget(frame)
        self.advanced_toggle = QPushButton("▸ Advanced: Spotify developer key, log file")
        self.advanced_toggle.setObjectName("fold")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self._fold)
        body.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        al = QVBoxLayout(self.advanced)
        al.setContentsMargins(0, 0, 0, 0)
        self.client_id = QLineEdit(s.spotify_client_id)
        self.client_id.setMinimumWidth(240)
        self.client_id.editingFinished.connect(self.save)
        al.addWidget(_item("Spotify Client ID",
                           "From your Spotify developer app. Changing it logs you out.",
                           self.client_id)[0])
        self.log_button = QPushButton("Open")
        self.log_button.clicked.connect(open_log_file)
        al.addWidget(_item("Log file", "Useful when something goes wrong", self.log_button)[0])
        self.advanced.setVisible(False)
        body.addWidget(self.advanced)
        body.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.done_button = QPushButton("Done")
        self.done_button.setObjectName("done")
        self.done_button.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(self.done_button)
        root = QVBoxLayout(self)
        root.addWidget(scroll, 1)
        root.addLayout(foot)

        self.refresh_spotify()
        self._loading = False
        self.load_playlists()

    # ---- display helpers ---------------------------------------------------------------
    def _song_count_text(self) -> str:
        try:
            counts = self.engine.selector.library.counts()
        except Exception:
            return ""
        total = sum(counts.values())
        unsorted = counts.get(MoodGroup.UNSORTED, 0)
        if not total:
            return "No songs yet"
        return (f"{total} songs · {unsorted} not sorted yet" if unsorted
                else f"{total} songs · all sorted into moods")

    def refresh_spotify(self) -> None:
        status = getattr(self.engine, "status", None)
        expired = status is not None and status.message == AUTH_EXPIRED
        self.spotify_status.setText("<span style='color:#e5484d'>●</span> Login expired. "
                                    "Use “Log in to Spotify” to log in again" if expired
                                    else "<span style='color:#1db954'>●</span> Connected")

    def _set_cameras(self, cameras) -> None:
        """Probed cameras plus the saved one (it may be busy, so probing can miss it)."""
        current = self.camera.currentData()
        chosen = self.settings.camera_index if current is None else current
        was_loading, self._loading = self._loading, True
        self.camera.clear()
        for i in sorted(set(cameras or []) | {self.settings.camera_index}):
            self.camera.addItem(f"Camera {i}" + (" (built-in)" if i == 0 else ""), i)
        self.camera.setCurrentIndex(max(self.camera.findData(chosen), 0))
        self._loading = was_loading

    def _fold(self, shown: bool) -> None:
        self.advanced.setVisible(shown)
        self.advanced_toggle.setText(("▾" if shown else "▸")
                                     + " Advanced: Spotify developer key, log file")

    # ---- actions -----------------------------------------------------------------------
    def _spotify_changed(self) -> None:
        if self._on_spotify_changed is not None:
            try:
                self._on_spotify_changed()
            except Exception:
                log.exception("Could not rebuild the Spotify client")

    def _style_changed(self, value: str) -> None:
        mode = Mode(value)
        if hasattr(self.engine, "set_mode"):
            self.engine.set_mode(mode)
        self.save()

    def _source_changed(self) -> None:
        if not self._loading:
            self.save()

    def _start_login_changed(self, on: bool) -> None:
        if self._loading:
            return
        if not self._autostart(on):
            self._loading = True
            self.start_login.setChecked(False)
            self._loading = False
            self.login_hint.setText("Starting at login isn't available on this system yet.")
            self.login_hint.setVisible(True)
            on = False
        self.settings.start_at_login = on
        self._persist()

    def _recalibrate(self) -> None:
        self.recalibrate_button.setEnabled(False)
        self.note.setText("Calibrating: sit normally and look at the screen…")
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
            self.playlist_status.setText("Couldn't load your playlists.")
            self.retry_button.show()
            return
        current = self.playlist.currentData()
        self._loading = True
        self.playlist.clear()
        self.playlist.addItem("Liked Songs", None)
        for pid, name, total in playlists:
            self.playlist.addItem(f"{name} ({total})", pid)
        if current is not None and self.playlist.findData(current) < 0:
            self.playlist.addItem("Current playlist", current)
        self.playlist.setCurrentIndex(max(self.playlist.findData(current), 0))
        self._loading = False
        self.playlist_status.setText("")
        self.playlist_status.setVisible(False)

    def done(self, result: int) -> None:
        self._runner.close()
        self._camera_runner.close()
        super().done(result)

    def _logout(self) -> None:
        logout_spotify()
        self._spotify_changed()
        self.spotify_status.setText("<span style='color:#9aa0aa'>●</span> Logged out. "
                                    "Use “Log in to Spotify” to log in again")

    def _persist(self) -> None:
        try:
            save_settings(self.settings)
        except Exception:
            log.exception("Could not save settings")

    def save(self) -> None:
        """Apply every control to the shared settings object, then persist."""
        if self._loading:
            return
        s = self.settings
        cam = self.camera.currentData()
        s.camera_index = cam if cam is not None else s.camera_index
        s.sensitivity = self.react.value() or s.sensitivity
        s.switch_mode = self.switch.value() or s.switch_mode
        s.mode = self.music_style.value() or s.mode
        minutes = self.away.currentData()
        s.away_pause_minutes = minutes if minutes is not None else s.away_pause_minutes
        new_id = self.client_id.text().strip()
        new_id_changed = new_id != s.spotify_client_id
        if new_id_changed:
            s.spotify_client_id = new_id
            logout_spotify()  # the old token belongs to the old app
        old_source = s.source_playlist_id
        s.source_playlist_id = self.playlist.currentData()
        self._persist()
        if new_id_changed:
            self._spotify_changed()  # the engine must use the new Client ID now
        if self.scan is not None and (s.source_playlist_id != old_source or new_id_changed):
            self.scan.rescan()
        self.worker.set_hold_seconds(HOLD_SECONDS.get(s.sensitivity, HOLD_SECONDS["normal"]))
