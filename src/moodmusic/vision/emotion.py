"""Emotion model wrapper. All HSEmotion imports live here so it stays swappable."""
from __future__ import annotations

import shutil
import urllib.request  # noqa: F401  (hsemotion_onnx uses urllib.request without importing it)
from pathlib import Path

import numpy as np
from hsemotion_onnx.facial_emotions import HSEmotionRecognizer

from moodmusic.resources import resource_path

from .types import EmotionReading

# Class order of the 8-class HSEmotion models (idx_to_class in hsemotion_onnx).
CLASSES = ("anger", "contempt", "disgust", "fear",
           "happiness", "neutral", "sadness", "surprise")


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def install_bundled_model(model_name: str, cache_dir: Path | None = None) -> bool:
    """Copy a bundled <model_name>.onnx into HSEmotion's cache (~/.hsemotion) if it is missing.

    hsemotion_onnx only looks there (and downloads otherwise), so this makes packaged builds
    work offline. Returns True when the cache holds the model afterwards.
    """
    cache = cache_dir if cache_dir is not None else Path.home() / ".hsemotion"
    target = cache / f"{model_name}.onnx"
    if target.is_file():
        return True
    bundled = resource_path(f"{model_name}.onnx")
    if bundled is None:
        return False
    cache.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    try:
        shutil.copyfile(bundled, tmp)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return True


class HSEmotionModel:
    def __init__(self, model_name: str = "enet_b0_8_va_mtl") -> None:
        install_bundled_model(model_name)
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
