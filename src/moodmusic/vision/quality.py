"""Frame quality checks. Frames are analysed in memory only, never saved."""
from __future__ import annotations

import numpy as np

from moodmusic.vision.types import FaceObservation, QualityReport

BLOCKED_MEAN_MAX = 15.0
BLOCKED_STD_MAX = 10.0
DARK_MEAN_MAX = 50.0
BACKLIGHT_DIFF_MIN = 90.0
MIN_FACE_WIDTH_FRACTION = 0.08
YAW_PROXY_MAX = 0.35

# MediaPipe face mesh landmark indices.
NOSE_TIP = 1
LEFT_EYE_OUTER = 33
RIGHT_EYE_OUTER = 263


def yaw_proxy(landmarks: np.ndarray) -> float:
    """Nose-tip asymmetry between the outer eye corners (0 = frontal)."""
    nose = float(landmarks[NOSE_TIP][0])
    left = float(landmarks[LEFT_EYE_OUTER][0])
    right = float(landmarks[RIGHT_EYE_OUTER][0])
    width = right - left
    if abs(width) < 1e-6:
        return 0.0
    return abs((nose - left) - (right - nose)) / abs(width)


def assess_quality(frame_bgr: np.ndarray, obs: FaceObservation) -> QualityReport:
    gray = frame_bgr.mean(axis=2) if frame_bgr.ndim == 3 else frame_bgr
    mean = float(gray.mean())
    if mean < BLOCKED_MEAN_MAX and float(gray.std()) < BLOCKED_STD_MAX:
        return QualityReport(False, "Camera looks blocked")
    if obs.face_count == 0:
        return QualityReport(False, "No face visible")
    if obs.face_count > 1:
        return QualityReport(False, "More than one face. Point the camera at just you")
    if mean < DARK_MEAN_MAX:
        return QualityReport(False, "Too dark. Add some light")

    if obs.bbox is not None:
        h, w = gray.shape[:2]
        x, y, bw, bh = obs.bbox  # (x, y, w, h) in pixels
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + bw), min(h, y + bh)
        if x1 > x0 and y1 > y0:
            mask = np.ones(gray.shape, bool)
            mask[y0:y1, x0:x1] = False
            if mask.any():
                face_mean = float(gray[y0:y1, x0:x1].mean())
                if float(gray[mask].mean()) - face_mean > BACKLIGHT_DIFF_MIN:
                    return QualityReport(False, "Strong light behind you")
        if bw < MIN_FACE_WIDTH_FRACTION * w:
            return QualityReport(False, "Face too small. Move closer")

    if obs.landmarks is not None and yaw_proxy(obs.landmarks) > YAW_PROXY_MAX:
        return QualityReport(False, "Turn to face the camera")
    return QualityReport(True, None)
