"""Persisted "not how I feel" corrections -> small valence/arousal bias.

Only numbers and group names are stored (no images, no text).
"""
from __future__ import annotations

import json
from pathlib import Path

from moodmusic.mood.groups import GROUP_CENTRES, MoodGroup

WINDOW = 50
GAIN = 0.5
CAP = 0.2


class CorrectionStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def record(self, predicted: MoodGroup, actual: MoodGroup, valence: float, arousal: float) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "predicted": predicted.value,
                "actual": actual.value,
                "valence": float(valence),
                "arousal": float(arousal),
            }
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def bias(self) -> tuple[float, float]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return (0.0, 0.0)
        dv: list[float] = []
        da: list[float] = []
        for line in lines[-WINDOW:]:
            try:
                d = json.loads(line)
                cv, ca = GROUP_CENTRES[MoodGroup(d["actual"])]
                dv.append(cv - float(d["valence"]))
                da.append(ca - float(d["arousal"]))
            except (ValueError, KeyError, TypeError):
                continue
        if not dv:
            return (0.0, 0.0)
        clamp = lambda x: max(-CAP, min(CAP, x))
        return (clamp(GAIN * sum(dv) / len(dv)), clamp(GAIN * sum(da) / len(da)))
