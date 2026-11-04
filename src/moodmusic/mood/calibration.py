"""Personal neutral-face calibration. Only numbers are persisted."""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from moodmusic.config import data_dir
from moodmusic.vision.types import EmotionReading

log = logging.getLogger(__name__)

MIN_SAMPLES = 20
NEUTRAL_TARGET = 0.6


@dataclass(frozen=True)
class Baseline:
    valence: float
    arousal: float
    neutral_prob_scale: float
    probs: dict[str, float] = field(default_factory=dict)  # resting emotion probabilities

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Baseline":
        return cls(
            valence=float(d["valence"]),
            arousal=float(d["arousal"]),
            neutral_prob_scale=float(d["neutral_prob_scale"]),
            probs={str(k): float(v) for k, v in (d.get("probs") or {}).items()},
        )


class Calibrator:
    def __init__(self, duration_s: float = 20.0) -> None:
        self.duration_s = duration_s
        self._samples: list[EmotionReading] = []
        self._first_t: float | None = None
        self._last_t: float | None = None

    def add(self, reading: EmotionReading, t: float) -> None:
        if self._first_t is None:
            self._first_t = t
        self._last_t = t
        self._samples.append(reading)

    @property
    def progress(self) -> float:
        if len(self._samples) < 2 or self.duration_s <= 0:
            return 0.0
        return min(1.0, (self._last_t - self._first_t) / self.duration_s)

    @property
    def done(self) -> bool:
        return self.progress >= 1.0

    def result(self) -> Baseline:
        if len(self._samples) < MIN_SAMPLES:
            raise ValueError(f"need at least {MIN_SAMPLES} samples, got {len(self._samples)}")
        med_neutral = statistics.median(s.probs.get("neutral", 0.0) for s in self._samples)
        return Baseline(
            valence=statistics.median(s.valence for s in self._samples),
            arousal=statistics.median(s.arousal for s in self._samples),
            neutral_prob_scale=NEUTRAL_TARGET / max(med_neutral, 0.1),
            probs={k: statistics.median(s.probs.get(k, 0.0) for s in self._samples)
                   for k in self._samples[0].probs},
        )


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def apply_baseline(r: EmotionReading, b: Baseline) -> EmotionReading:
    probs = dict(r.probs)
    if "neutral" in probs:
        probs["neutral"] = min(1.0, probs["neutral"] * b.neutral_prob_scale)
    return replace(
        r,
        probs=probs,
        valence=_clamp(r.valence - b.valence),
        arousal=_clamp(r.arousal - b.arousal),
    )


def _default_path() -> Path:
    return data_dir() / "baseline.json"


def load_baseline(path: Path | None = None) -> Baseline | None:
    path = path or _default_path()
    try:
        return Baseline.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        log.warning("Ignoring unreadable baseline file")
        return None


def save_baseline(b: Baseline, path: Path | None = None) -> None:
    path = path or _default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(b.to_dict()), encoding="utf-8")
