import math

import numpy as np
import pytest

from moodmusic.vision.signals import FrameSignals, extract_signals
from moodmusic.vision.types import EmotionReading, FaceObservation

# Neutral frontal face in normalized image coords (x right, y down).
EYE_R_OUT, EYE_R_IN, EYE_L_IN, EYE_L_OUT = 33, 133, 362, 263  # subject's right eye is image-left
NOSE, CHIN, IRIS_R, IRIS_L = 1, 152, 468, 473
FOREHEAD, BRIDGE = 10, 168
HALF_SPAN = 0.10  # half the outer-corner distance


def make_obs(yaw_deg: float = 0.0, iris_dx: float = 0.0, blend: dict | None = None,
             pitch_dz: float = 0.0, chin_y: float = 0.70, iris_dy: float = 0.0,
             size=(640, 480)) -> FaceObservation:
    pts = np.zeros((478, 3), dtype=np.float32)
    pts[EYE_R_OUT] = (0.40, 0.40, 0)
    pts[EYE_R_IN] = (0.46, 0.40, 0)
    pts[EYE_L_IN] = (0.54, 0.40, 0)
    pts[EYE_L_OUT] = (0.60, 0.40, 0)
    pts[NOSE] = (0.50 + math.sin(math.radians(yaw_deg)) * HALF_SPAN, 0.52, 0)
    pts[CHIN] = (0.50, chin_y, 0)
    pts[BRIDGE] = (0.50, 0.40, 0)
    pts[FOREHEAD] = (0.50, 0.25, pitch_dz)  # z > 0 = farther from the camera
    # iris_dx is a fraction of each eye's half-width (0.03); negative = image-left
    # iris_dy is a fraction of the eye half-width in *pixels* (so y is scaled by w/h)
    dy = iris_dy * 0.03 * size[0] / size[1]
    pts[IRIS_R] = (0.43 + iris_dx * 0.03, 0.40 - dy, 0)
    pts[IRIS_L] = (0.57 + iris_dx * 0.03, 0.40 - dy, 0)
    return FaceObservation(1, (100, 100, 200, 250), dict(blend or {}), pts, size)


READING = EmotionReading({"neutral": 0.7, "happiness": 0.3}, 0.2, -0.1)


def test_no_face_returns_face_false():
    s = extract_signals(FaceObservation(0), None, None)
    assert s.face is False and s.gaze_on_screen is False and s.smile == 0.0


def test_frontal_face_gaze_on_screen():
    s = extract_signals(make_obs(), READING, None)
    assert s.face is True
    assert s.gaze_on_screen is True
    assert abs(s.head_yaw) < 5
    assert s.valence == pytest.approx(0.2) and s.emotion["neutral"] == pytest.approx(0.7)


def test_iris_shift_left_reads_gaze_away():
    s = extract_signals(make_obs(iris_dx=-0.7), READING, None)
    assert s.gaze_x < -0.35
    assert s.gaze_on_screen is False


def test_head_turn_30deg_reads_off_screen():
    s = extract_signals(make_obs(yaw_deg=30), READING, None)
    assert s.head_yaw == pytest.approx(30, abs=3)
    assert s.gaze_on_screen is False


def test_smile_and_cheek_from_blendshapes():
    s = extract_signals(make_obs(blend={"mouthSmileLeft": .8, "mouthSmileRight": .6,
                                        "cheekSquintLeft": .4, "cheekSquintRight": .4}),
                        READING, None)
    assert s.smile == pytest.approx(.7)
    assert s.cheek_squint == pytest.approx(.4)


def test_eye_open_from_blinks():
    s = extract_signals(make_obs(blend={"eyeBlinkLeft": .9, "eyeBlinkRight": .9}), READING, None)
    assert s.eye_open == pytest.approx(.1)


def test_mouth_motion_uses_previous_frame():
    first = extract_signals(make_obs(blend={"jawOpen": .1, "mouthClose": .0}), READING, None)
    assert first.mouth_motion == 0.0
    second = extract_signals(make_obs(blend={"jawOpen": .4, "mouthClose": .1}), READING, first)
    assert second.mouth_motion == pytest.approx(.3 + .1)
    assert isinstance(second, FrameSignals)


def test_missing_reading_gives_zero_emotion():
    s = extract_signals(make_obs(), None, None)
    assert s.face is True and s.valence == 0.0 and s.emotion == {}


def test_pitch_ignores_jaw_opening():
    closed = extract_signals(make_obs(chin_y=0.70), READING, None)
    talking = extract_signals(make_obs(chin_y=0.76), READING, None)  # jaw drops ~6% of height
    assert talking.head_pitch == pytest.approx(closed.head_pitch, abs=0.5)
    assert abs(closed.head_pitch) < 2


def test_pitch_from_forehead_depth():
    up = extract_signals(make_obs(pitch_dz=0.05), READING, None)
    down = extract_signals(make_obs(pitch_dz=-0.05), READING, None)
    assert up.head_pitch > 10 and down.head_pitch < -10


def test_gaze_y_in_pixel_units():
    s = extract_signals(make_obs(iris_dy=0.5), READING, None)  # half an eye-width up
    assert s.gaze_y == pytest.approx(0.5, abs=0.02)
    assert s.gaze_x == pytest.approx(0.0, abs=0.02)


def test_roll_uses_pixel_units():
    obs = make_obs()
    obs.landmarks[EYE_L_OUT][1] = 0.40 + 0.20 * 640 / 480 * math.tan(math.radians(10))
    s = extract_signals(obs, READING, None)
    assert s.head_roll == pytest.approx(10, abs=0.5)
