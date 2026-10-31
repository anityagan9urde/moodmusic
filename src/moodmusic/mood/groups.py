"""Mood groups, valence/arousal classification and "lift" targeting."""
from __future__ import annotations

import random
from enum import Enum

NEUTRAL_ZONE = 0.15
NEUTRAL_PROB_THRESHOLD = 0.6
LIFT_CHILL_TO_UPBEAT_PROB = 0.2


class MoodGroup(str, Enum):
    """Song groups. Values are stored in the library DB, so never rename them."""
    FOCUS = "focus"
    PROFOUND = "profound"
    ROMANTIC = "romantic"
    CHILL = "chill"
    UPBEAT = "upbeat"
    PARTY = "party"
    MELANCHOLY = "melancholy"
    INTENSE = "intense"
    UNSORTED = "unsorted"

    @property
    def label(self) -> str:
        return self.name.capitalize()

    @property
    def emoji(self) -> str:
        return _EMOJI[self]


_EMOJI = {
    MoodGroup.FOCUS: "🎧",
    MoodGroup.PROFOUND: "🌌",
    MoodGroup.ROMANTIC: "💞",
    MoodGroup.CHILL: "😌",
    MoodGroup.UPBEAT: "😄",
    MoodGroup.PARTY: "🎉",
    MoodGroup.MELANCHOLY: "😔",
    MoodGroup.INTENSE: "🔥",
    MoodGroup.UNSORTED: "❔",
}


# LEGACY (old five-label pipeline; removed in the mood-states Task 10).
# Target (valence, arousal) centre of each group; shared by smoother and corrections.
GROUP_CENTRES: dict[MoodGroup, tuple[float, float]] = {
    MoodGroup.UPBEAT: (0.5, 0.5),
    MoodGroup.CHILL: (0.5, -0.5),
    MoodGroup.MELANCHOLY: (-0.5, -0.5),
    MoodGroup.INTENSE: (-0.5, 0.5),
    MoodGroup.FOCUS: (0.0, 0.0),
    MoodGroup.PROFOUND: (-0.1, -0.4),
    MoodGroup.ROMANTIC: (0.4, -0.2),
    MoodGroup.PARTY: (0.6, 0.7),
    MoodGroup.UNSORTED: (0.0, 0.0),
}


class Mode(str, Enum):
    MATCH = "match"
    LIFT = "lift"


_NEAREST = {  # intent-ordered fallback between song groups
    MoodGroup.FOCUS: [MoodGroup.CHILL, MoodGroup.PROFOUND, MoodGroup.ROMANTIC, MoodGroup.UPBEAT, MoodGroup.MELANCHOLY, MoodGroup.PARTY, MoodGroup.INTENSE],
    MoodGroup.PROFOUND: [MoodGroup.MELANCHOLY, MoodGroup.CHILL, MoodGroup.FOCUS, MoodGroup.ROMANTIC, MoodGroup.UPBEAT, MoodGroup.INTENSE, MoodGroup.PARTY],
    MoodGroup.ROMANTIC: [MoodGroup.CHILL, MoodGroup.PROFOUND, MoodGroup.UPBEAT, MoodGroup.MELANCHOLY, MoodGroup.FOCUS, MoodGroup.PARTY, MoodGroup.INTENSE],
    MoodGroup.CHILL: [MoodGroup.ROMANTIC, MoodGroup.FOCUS, MoodGroup.PROFOUND, MoodGroup.UPBEAT, MoodGroup.MELANCHOLY, MoodGroup.PARTY, MoodGroup.INTENSE],
    MoodGroup.UPBEAT: [MoodGroup.PARTY, MoodGroup.ROMANTIC, MoodGroup.CHILL, MoodGroup.INTENSE, MoodGroup.FOCUS, MoodGroup.PROFOUND, MoodGroup.MELANCHOLY],
    MoodGroup.PARTY: [MoodGroup.UPBEAT, MoodGroup.INTENSE, MoodGroup.ROMANTIC, MoodGroup.CHILL, MoodGroup.FOCUS, MoodGroup.PROFOUND, MoodGroup.MELANCHOLY],
    MoodGroup.MELANCHOLY: [MoodGroup.PROFOUND, MoodGroup.CHILL, MoodGroup.ROMANTIC, MoodGroup.FOCUS, MoodGroup.UPBEAT, MoodGroup.INTENSE, MoodGroup.PARTY],
    MoodGroup.INTENSE: [MoodGroup.PARTY, MoodGroup.UPBEAT, MoodGroup.FOCUS, MoodGroup.CHILL, MoodGroup.PROFOUND, MoodGroup.ROMANTIC, MoodGroup.MELANCHOLY],
}


def classify(valence: float, arousal: float, neutral_prob: float) -> MoodGroup:
    """Map valence/arousal (-1..1) and neutral probability to a mood group.

    Never returns UNSORTED.
    """
    if neutral_prob >= NEUTRAL_PROB_THRESHOLD:
        return MoodGroup.FOCUS
    if abs(valence) < NEUTRAL_ZONE and abs(arousal) < NEUTRAL_ZONE:
        return MoodGroup.FOCUS
    if valence >= 0:
        return MoodGroup.UPBEAT if arousal >= 0 else MoodGroup.CHILL
    return MoodGroup.INTENSE if arousal >= 0 else MoodGroup.MELANCHOLY


def lift_target(current: MoodGroup, rng: random.Random) -> MoodGroup:
    """One gentle step toward a better mood; re-evaluated after each song."""
    if current in (MoodGroup.MELANCHOLY, MoodGroup.INTENSE):
        return MoodGroup.CHILL
    if current == MoodGroup.CHILL:
        return MoodGroup.UPBEAT if rng.random() < LIFT_CHILL_TO_UPBEAT_PROB else MoodGroup.CHILL
    return current


def target_group(current: MoodGroup, mode: Mode, rng: random.Random) -> MoodGroup:
    if current == MoodGroup.UNSORTED:
        return MoodGroup.FOCUS
    if mode == Mode.LIFT:
        return lift_target(current, rng)
    return current


def nearest_groups(g: MoodGroup) -> list[MoodGroup]:
    """Fallback order of other groups, closest first; never includes UNSORTED."""
    if g == MoodGroup.UNSORTED:
        return [MoodGroup.FOCUS, *_NEAREST[MoodGroup.FOCUS]]
    return list(_NEAREST[g])
