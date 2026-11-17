"""'Not how I feel' corrections as a capped per-state score bias (numbers only)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from moodmusic.mood.states import FaceState

log = logging.getLogger(__name__)

STEP = 0.05
BIAS_CAP = 0.25
WINDOW = 50


class StateCorrections:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._bias: dict[FaceState, float] | None = None

    def record(self, predicted: FaceState, actual: FaceState) -> None:
        if predicted == actual:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"predicted": predicted.value, "actual": actual.value}) + "\n")
        self._bias = None

    def bias(self) -> dict[FaceState, float]:
        if self._bias is None:
            self._bias = self._compute()
        return dict(self._bias)

    def _compute(self) -> dict[FaceState, float]:
        try:
            text = self._path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return {}
        except OSError:
            log.warning("State corrections unreadable; ignoring")
            return {}
        records: list[tuple[FaceState, FaceState]] = []
        for line in text.splitlines():
            try:
                d = json.loads(line)
                records.append((FaceState(d["predicted"]), FaceState(d["actual"])))
            except (ValueError, KeyError, TypeError):
                continue
        bias: dict[FaceState, float] = {}
        for predicted, actual in records[-WINDOW:]:
            bias[actual] = bias.get(actual, 0.0) + STEP
            bias[predicted] = bias.get(predicted, 0.0) - STEP
        return {s: max(-BIAS_CAP, min(BIAS_CAP, v)) for s, v in bias.items() if abs(v) > 1e-9}
