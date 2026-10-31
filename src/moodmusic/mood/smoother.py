"""EMA smoothing of readings plus a hold-time rule for group changes."""
from __future__ import annotations

from dataclasses import dataclass, field

from moodmusic.mood.groups import GROUP_CENTRES, MoodGroup, classify
from moodmusic.vision.types import EmotionReading


@dataclass(frozen=True)
class MoodState:
    group: MoodGroup = MoodGroup.FOCUS
    since: float = 0.0
    valence: float = 0.0
    arousal: float = 0.0
    probs: dict[str, float] = field(default_factory=dict)
    candidate: MoodGroup | None = None


class MoodSmoother:
    def __init__(self, hold_seconds: float, alpha: float = 0.15) -> None:
        self._hold = hold_seconds
        self._alpha = alpha
        self._state = MoodState()
        self._seeded = False
        self._candidate_start = 0.0

    @property
    def state(self) -> MoodState:
        return self._state

    def set_hold(self, seconds: float) -> None:
        self._hold = seconds

    def update(self, r: EmotionReading, t: float) -> MoodState:
        s = self._state
        if not self._seeded:
            self._seeded = True
            v, a, probs = r.valence, r.arousal, dict(r.probs)
            since = t
        else:
            k = self._alpha
            v = s.valence + k * (r.valence - s.valence)
            a = s.arousal + k * (r.arousal - s.arousal)
            keys = set(s.probs) | set(r.probs)
            probs = {
                key: s.probs.get(key, 0.0) + k * (r.probs.get(key, 0.0) - s.probs.get(key, 0.0))
                for key in keys
            }
            since = s.since
        group, candidate = s.group, s.candidate
        seen = classify(v, a, probs.get("neutral", 0.0))
        if seen == group:
            candidate = None
        else:
            if seen != candidate:
                candidate = seen
                self._candidate_start = t
            if t - self._candidate_start >= self._hold:
                group, since, candidate = seen, t, None
        self._state = MoodState(group, since, v, a, probs, candidate)
        return self._state

    def force(self, group: MoodGroup, t: float) -> MoodState:
        v, a = GROUP_CENTRES[group]
        self._seeded = True
        self._state = MoodState(group, t, v, a, dict(self._state.probs), None)
        return self._state
