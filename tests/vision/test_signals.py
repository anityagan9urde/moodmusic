import math

import numpy as np
import pytest

from moodmusic.vision.signals import FrameSignals, extract_signals
from moodmusic.vision.types import EmotionReading, FaceObservation

# Neutral frontal face in normalized image coords (x right, y down).
EYE_R_OUT, EYE_R_IN, EYE_L_IN, EYE_L_OUT = 33, 133, 362, 263  # subject's right eye is image-left
NOSE, CHIN, IRIS_R, IRIS_L = 1, 152, 468, 473
HALF_SPAN = 0.10  # half the outer-corner distance


def make_obs(yaw_deg: float = 0.0, iris_dx: float = 0.0, blend: dict | None = None) -> FaceObservation:
    pts = np.zeros((478, 3), dtype=np.float32)
    pts[EYE_R_OUT] = (0.40, 0.40, 0)
    pts[EYE_R_IN] = (0.46, 0.40, 0)
    pts[EYE_L_IN] = (0.54, 0.40, 0)
    pts[EYE_L_OUT] = (0.60, 0.40, 0)
    pts[NOSE] = (0.50 + math.sin(math.radians(yaw_deg)) * HALF_SPAN, 0.52, 0)
    pts[CHIN] = (0.50, 0.70, 0)
    # iris_dx is a fraction of each eye's half-width (0.03); negative = image-left
    pts[IRIS_R] = (0.43 + iris_dx * 0.03, 0.40, 0)
    pts[IRIS_L] = (0.57 + iris_dx * 0.03, 0.40, 0)
    return FaceObservation(1, (100, 100, 200, 250), dict(blend or {}), pts)


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
