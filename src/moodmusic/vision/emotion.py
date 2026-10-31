"""Emotion model wrapper. All HSEmotion imports live here so it stays swappable."""
from __future__ import annotations

import urllib.request  # noqa: F401  (hsemotion_onnx uses urllib.request without importing it)

import numpy as np
from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

from .types import EmotionReading

# Class order of the 8-class HSEmotion models (idx_to_class in hsemotion_onnx).
CLASSES = ("anger", "contempt", "disgust", "fear",
           "happiness", "neutral", "sadness", "surprise")


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


class HSEmotionModel:
    def __init__(self, model_name: str = "enet_b0_8_va_mtl") -> None:
        self._rec = HSEmotionRecognizer(model_name=model_name)

    def predict(self, face_rgb: np.ndarray) -> EmotionReading:
        _, scores = self._rec.predict_emotions(face_rgb, logits=True)
        scores = np.asarray(scores, dtype=float).reshape(-1)
        logits = scores[:8]
        e = np.exp(logits - logits.max())
        p = e / e.sum()
        return EmotionReading(
            probs={c: float(v) for c, v in zip(CLASSES, p)},
            valence=_clamp(scores[8]),
            arousal=_clamp(scores[9]),
        )
