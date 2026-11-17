import numpy as np

from moodmusic.vision.camera import CameraSource, list_cameras


class FakeCap:
    def __init__(self, script, opened=True):
        self.script = list(script)
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened and not self.released

    def read(self):
        ok = self.script.pop(0) if self.script else True
        return (True, np.zeros((4, 4, 3), np.uint8)) if ok else (False, None)

    def release(self):
        self.released = True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_reconnect_cycle():
    clock = Clock()
    caps = [FakeCap([True, False, False, False]), FakeCap([True])]
    cam = CameraSource(0, capture_factory=lambda *a: caps.pop(0), clock=clock)
    assert cam.read() is not None and cam.status == "ok"
    assert cam.read() is None and cam.status == "ok"
    assert cam.read() is None
    assert cam.read() is None and cam.status == "reconnecting"
    clock.t = 1.0
    assert cam.read() is None and cam.status == "reconnecting"
    clock.t = 2.5
    assert cam.read() is not None and cam.status == "ok"


def test_unavailable_when_never_opened():
    clock = Clock()
    cam = CameraSource(0, capture_factory=lambda *a: FakeCap([], opened=False), clock=clock)
    assert cam.status == "unavailable"
    assert cam.read() is None and cam.status == "unavailable"


def test_read_never_raises():
    class Boom(FakeCap):
        def read(self):
            raise RuntimeError("x")

    cam = CameraSource(0, capture_factory=lambda *a: Boom([]), clock=Clock())
    for _ in range(5):
        assert cam.read() is None


def test_release_idempotent():
    cap = FakeCap([])
    cam = CameraSource(0, capture_factory=lambda *a: cap, clock=Clock())
    cam.release()
    cam.release()
    assert cap.released


def test_list_cameras_releases_each():
    made = []

    def factory(i, *a):
        c = FakeCap([], opened=i in (0, 2))
        made.append(c)
        return c

    assert list_cameras(max_index=3, capture_factory=factory) == [0, 2]
    assert len(made) == 3 and all(c.released for c in made)
