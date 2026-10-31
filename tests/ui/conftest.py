import pytest
from PySide6.QtCore import QObject, Signal

from moodmusic.app.engine import EngineStatus
from moodmusic.mood.groups import MoodGroup
from moodmusic.music.library import Song
from moodmusic.music.selector import Pick


class FakeEngine:
    def __init__(self):
        from moodmusic.config import Settings
        self.settings = Settings()
        self.status = EngineStatus("ok", "")
        self.current_pick = None
        self.listeners = []
        self.history = []
        self.devices = []
        self.calls = []

    def notify(self):
        for fn in list(self.listeners):
            fn()

    def available_devices(self):
        return self.devices

    def set_mode(self, mode):
        self.calls.append(("set_mode", mode))

    def set_enabled(self, enabled):
        self.calls.append(("set_enabled", enabled))

    def set_device(self, device_id):
        self.calls.append(("set_device", device_id))

    def wrong_vibe(self, group):
        self.calls.append(("wrong_vibe", group))

    def skip(self):
        self.calls.append(("skip",))

    def previous(self):
        self.calls.append(("previous",))

    def toggle_pause(self):
        self.calls.append(("toggle_pause",))


class FakeWorker(QObject):
    mood = Signal(object)
    quality = Signal(object)
    face_present = Signal(bool)
    reading = Signal(object)
    preview = Signal(object)
    camera_status = Signal(str)
    calibration_progress = Signal(float)
    calibration_done = Signal(object)
    features_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.calls = []

    def set_preview(self, enabled):
        self.calls.append(("set_preview", enabled))

    def force_mood(self, group):
        self.calls.append(("force_mood", group))


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def worker():
    return FakeWorker()


@pytest.fixture
def pick():
    song = Song("spotify:track:1", "Holocene", "Bon Iver", None, MoodGroup.CHILL)
    return Pick(song, MoodGroup.CHILL, "calm + positive", None)
