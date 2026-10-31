"""Plain data types shared by the vision pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class EmotionReading:
    probs: dict[str, float]
    valence: float
    arousal: float


class EmotionModel(Protocol):
    def predict(self, face_rgb: np.ndarray) -> EmotionReading: ...


@dataclass
class FaceObservation:
    face_count: int
    bbox: tuple[int, int, int, int] | None = None
    blendshapes: dict[str, float] = field(default_factory=dict)
    landmarks: np.ndarray | None = None


@dataclass(frozen=True)
class QualityReport:
    ok: bool
    issue: str | None = None
