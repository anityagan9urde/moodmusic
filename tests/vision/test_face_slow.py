import numpy as np
import pytest

from moodmusic.config import data_dir

MODEL = data_dir() / "models" / "face_landmarker.task"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not MODEL.exists(), reason="face landmarker model not cached"),
]


def test_tracker_handles_blank_frame_and_repeated_timestamps():
    from moodmusic.vision.face import FaceTracker

    t = FaceTracker()
    try:
        blank = np.full((480, 640, 3), 128, np.uint8)
        assert t.process(blank, 100).face_count == 0
        assert t.process(blank, 100).face_count == 0  # equal timestamp guarded
        assert t.process(blank, 50).face_count == 0  # decreasing guarded
    finally:
        t.close()
