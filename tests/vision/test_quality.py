import numpy as np

from moodmusic.vision.quality import assess_quality
from moodmusic.vision.types import FaceObservation

H, W = 480, 640


def frame(value, noise=20):
    rng = np.random.default_rng(0)
    f = rng.normal(value, noise, (H, W, 3)).clip(0, 255)
    return f.astype(np.uint8)


def face(bbox=(220, 120, 200, 240), count=1, landmarks=None):
    return FaceObservation(face_count=count, bbox=bbox, landmarks=landmarks)


def lm(nose_x=0.5, left=0.4, right=0.6):
    pts = np.zeros((468, 3))
    pts[1] = (nose_x, 0.5, 0)
    pts[33] = (left, 0.4, 0)
    pts[263] = (right, 0.4, 0)
    return pts


def test_black_frame_blocked():
    f = np.zeros((H, W, 3), np.uint8)
    assert assess_quality(f, FaceObservation(0)).issue == "Camera looks blocked"


def test_blocked_beats_face_present():
    f = np.zeros((H, W, 3), np.uint8)
    assert assess_quality(f, face()).issue == "Camera looks blocked"


def test_no_face():
    assert assess_quality(frame(128), FaceObservation(0)).issue == "No face visible"


def test_multiple_faces():
    r = assess_quality(frame(128), face(count=2))
    assert r.issue == "More than one face. Point the camera at just you"


def test_too_dark():
    r = assess_quality(frame(25), face())
    assert r.issue == "Too dark. Add some light"


def test_backlit():
    f = np.full((H, W, 3), 230, np.uint8)
    x, y, w, h = 220, 120, 200, 240
    f[y:y + h, x:x + w] = 60
    r = assess_quality(f, face((x, y, w, h)))
    assert r.issue == "Strong light behind you"


def test_face_too_small():
    r = assess_quality(frame(128), face((300, 200, 40, 50)))
    assert r.issue == "Face too small. Move closer"


def test_turned_away():
    r = assess_quality(frame(128), face(landmarks=lm(nose_x=0.57)))
    assert r.issue == "Turn to face the camera"


def test_good_frame():
    r = assess_quality(frame(128), face(landmarks=lm()))
    assert r.ok and r.issue is None


def test_degenerate_eye_width_does_not_crash():
    r = assess_quality(frame(128), face(landmarks=lm(left=0.5, right=0.5)))
    assert r.ok
