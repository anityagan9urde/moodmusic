"""MediaPipe FaceLandmarker wrapper (VIDEO mode). Frames stay in memory."""
from __future__ import annotations

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from moodmusic.vision.models import face_landmarker_path
from moodmusic.vision.types import FaceObservation


def crop_face(frame_bgr: np.ndarray, bbox: tuple[int, int, int, int],
              margin: float = 0.2) -> np.ndarray:
    """Crop bbox (x, y, w, h in pixels) plus margin; returns RGB."""
    h, w = frame_bgr.shape[:2]
    x, y, bw, bh = bbox
    mx, my = int(bw * margin), int(bh * margin)
    x0, y0 = max(0, x - mx), max(0, y - my)
    x1, y1 = min(w, x + bw + mx), min(h, y + bh + my)
    return cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)


def _area(pts: np.ndarray) -> float:
    return float(np.ptp(pts[:, 0]) * np.ptp(pts[:, 1]))


class FaceTracker:
    def __init__(self, model_path=None):
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path or face_landmarker_path())),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=2,
            output_face_blendshapes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_ts = -1

    def process(self, frame_bgr: np.ndarray, timestamp_ms: int) -> FaceObservation:
        ts = max(int(timestamp_ms), self._last_ts + 1)  # must strictly increase
        self._last_ts = ts
        rgb = np.ascontiguousarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, ts)
        faces = result.face_landmarks
        if not faces:
            return FaceObservation(face_count=0)
        all_pts = [np.array([[p.x, p.y, p.z] for p in f], dtype=np.float32) for f in faces]
        i = max(range(len(all_pts)), key=lambda k: _area(all_pts[k]))
        pts = all_pts[i]
        h, w = frame_bgr.shape[:2]
        x0, y0 = int(pts[:, 0].min() * w), int(pts[:, 1].min() * h)
        x1, y1 = int(pts[:, 0].max() * w), int(pts[:, 1].max() * h)
        blend = {}
        if result.face_blendshapes and len(result.face_blendshapes) > i:
            blend = {c.category_name: float(c.score) for c in result.face_blendshapes[i]}
        return FaceObservation(len(faces), (x0, y0, x1 - x0, y1 - y0), blend, pts)

    def close(self) -> None:
        self._landmarker.close()
