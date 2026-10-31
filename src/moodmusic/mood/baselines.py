"""The user's own normal for each signal: short calibration + passive rolling medians."""
from __future__ import annotations

import json
import logging
import os
import statistics
from collections import deque
from pathlib import Path

from moodmusic.config import data_dir
from moodmusic.mood.features import Features

log = logging.getLogger(__name__)

# Population defaults, used until the user's own data exists (retuned from the signal recording).
DEFAULTS: dict[str, float] = {
    "blink_rate_per_min_60s": 15.0,
    "mean_blink_ms_60s": 200.0,
    "perclos_60s": 0.05,
    "head_motion_30s": 4.0,
    "brow_down_30s": 0.15,
    "mouth_press_30s": 0.1,
    "smile_10s": 0.05,
    "gaze_on_ratio_30s": 0.85,
    "head_droop_deg_240s": -5.0,
    "brow_inner_up_10s": 0.05,
    "head_tilt_10s": 2.0,
}
KEYS = tuple(DEFAULTS)
REST_KEYS = ("brow_down_30s", "mouth_press_30s", "smile_10s", "gaze_on_ratio_30s",
             "head_droop_deg_240s", "brow_inner_up_10s", "head_tilt_10s")
SAMPLE_EVERY_S = 15
# ~8 h of 15 s samples: slow enough that an hour of tiredness doesn't become "normal",
# and samples are only taken while no other state is active (see update(sample=...)).
MAX_SAMPLES = 2000
MIN_SAMPLES = 12  # three minutes of samples before the passive median is trusted
WARM_AFTER_S = 1800.0
FACE_PRESENT = 0.5


class PersonalBaselines:
    def __init__(self) -> None:
        self._samples: dict[str, deque[float]] = {k: deque(maxlen=MAX_SAMPLES) for k in KEYS}
        self._rest: dict[str, float] = {}
        self._since_sample = 0.0
        self._median_cache: dict[str, float] = {}
        self.observed_s = 0.0
        self.screen_center: tuple[float, float, float] | None = None  # gaze_x, gaze_y, yaw

    @property
    def warm(self) -> bool:
        return self.observed_s >= WARM_AFTER_S

    def update(self, f: Features, dt: float, sample: bool = True) -> None:
        """Count face time; sample "normal" only when `sample` (i.e. no other state active)."""
        if f.face_ratio_10s < FACE_PRESENT:
            return
        self.observed_s += dt
        if not sample:
            return
        self._since_sample += dt
        if self._since_sample + 1e-9 < SAMPLE_EVERY_S:
            return
        self._since_sample = 0.0
        for k in KEYS:
            self._samples[k].append(float(getattr(f, k)))
        self._median_cache.clear()

    def calibrate_rest(self, f: Features) -> None:
        for k in REST_KEYS:
            self._rest[k] = float(getattr(f, k))

    def get(self, key: str, default: float | None = None) -> float:
        samples = self._samples.get(key)
        if samples is not None and len(samples) >= MIN_SAMPLES:
            if key not in self._median_cache:
                self._median_cache[key] = statistics.median(samples)
            return self._median_cache[key]
        if key in self._rest:
            return self._rest[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return 0.0 if default is None else default

    def to_dict(self) -> dict:
        return {"samples": {k: list(v) for k, v in self._samples.items()},
                "rest": dict(self._rest), "observed_s": self.observed_s,
                "screen_center": list(self.screen_center) if self.screen_center else None}

    @classmethod
    def from_dict(cls, d: dict) -> "PersonalBaselines":
        b = cls()
        for k, values in (d.get("samples") or {}).items():
            if k in b._samples:
                b._samples[k].extend(float(v) for v in values)
        b._rest = {k: float(v) for k, v in (d.get("rest") or {}).items() if k in REST_KEYS}
        b.observed_s = float(d.get("observed_s", 0.0))
        center = d.get("screen_center")
        if center and len(center) == 3:
            b.screen_center = tuple(float(v) for v in center)
        return b


def _default_path() -> Path:
    return data_dir() / "signal_baselines.json"


def load_baselines(path: Path | None = None) -> PersonalBaselines:
    path = path or _default_path()
    try:
        return PersonalBaselines.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except FileNotFoundError:
        return PersonalBaselines()
    except (OSError, ValueError, TypeError, AttributeError):
        log.warning("Signal baselines unreadable; starting fresh")
        return PersonalBaselines()


def save_baselines(b: PersonalBaselines, path: Path | None = None) -> None:
    path = Path(path or _default_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(b.to_dict()), encoding="utf-8")
    os.replace(tmp, path)
