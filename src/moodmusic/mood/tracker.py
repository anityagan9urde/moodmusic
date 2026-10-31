"""Turns per-moment state decisions into a stable face state (hold time, corrections)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from moodmusic.mood.features import Features
from moodmusic.mood.states import EVIDENCE_WINDOW_S, FaceState

FORCED_REASON = "you said so"


@dataclass(frozen=True)
class FaceMood:
    state: FaceState = FaceState.FOCUSED
    since: float = 0.0
    reason: str = ""
    valence: float = 0.0
    arousal: float = 0.0
    probs: dict[str, float] = field(default_factory=dict)
    candidate: FaceState | None = None


class StateTracker:
    def __init__(self, hold_seconds: float) -> None:
        self._hold = hold_seconds
        self._state = FaceMood()
        self._candidate_start = 0.0

    @property
    def state(self) -> FaceMood:
        return self._state

    def set_hold(self, seconds: float) -> None:
        self._hold = seconds

    def update(self, decision: tuple[FaceState | None, str], f: Features, t: float) -> FaceMood:
        seen, reason = decision
        s = replace(self._state, valence=f.valence_30s, arousal=f.arousal_30s,
                    probs=dict(f.emotion_30s))
        if seen is None:  # nothing clear: hold the state and keep the candidate timer
            self._state = s
            return s
        if seen == s.state:
            self._state = replace(s, reason=reason, candidate=None)
            return self._state
        if seen != s.candidate:
            self._candidate_start = t
        needed = self._hold + EVIDENCE_WINDOW_S.get(seen, 0)  # slow states: sustained
        if t - self._candidate_start >= needed:
            self._state = replace(s, state=seen, since=t, reason=reason, candidate=None)
        else:
            self._state = replace(s, candidate=seen)
        return self._state

    def force(self, state: FaceState, t: float) -> FaceMood:
        self._state = replace(self._state, state=state, since=t, reason=FORCED_REASON,
                              candidate=None)
        return self._state
