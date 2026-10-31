"""Mood groups, valence/arousal classification and "lift" targeting."""
from __future__ import annotations

import random
from enum import Enum

NEUTRAL_ZONE = 0.15
NEUTRAL_PROB_THRESHOLD = 0.6
LIFT_CHILL_TO_UPBEAT_PROB = 0.2


class MoodGroup(str, Enum):
    UPBEAT = "upbeat"
    CHILL = "chill"
    MELANCHOLY = "melancholy"
    INTENSE = "intense"
    FOCUS = "focus"
    UNSORTED = "unsorted"

    @property
    def label(self) -> str:
        return self.name.capitalize()

    @property
    def emoji(self) -> str:
        return _EMOJI[self]


_EMOJI = {
    MoodGroup.UPBEAT: "😄",
    MoodGroup.CHILL: "😌",
    MoodGroup.MELANCHOLY: "😔",
    MoodGroup.INTENSE: "😤",
    MoodGroup.FOCUS: "🎧",
    MoodGroup.UNSORTED: "❔",
}


class Mode(str, Enum):
    MATCH = "match"
    LIFT = "lift"


_NEAREST = {
    MoodGroup.UPBEAT: [MoodGroup.CHILL, MoodGroup.INTENSE, MoodGroup.FOCUS, MoodGroup.MELANCHOLY],
    MoodGroup.CHILL: [MoodGroup.FOCUS, MoodGroup.UPBEAT, MoodGroup.MELANCHOLY, MoodGroup.INTENSE],
    MoodGroup.MELANCHOLY: [MoodGroup.CHILL, MoodGroup.FOCUS, MoodGroup.INTENSE, MoodGroup.UPBEAT],
    MoodGroup.INTENSE: [MoodGroup.UPBEAT, MoodGroup.FOCUS, MoodGroup.CHILL, MoodGroup.MELANCHOLY],
    MoodGroup.FOCUS: [MoodGroup.CHILL, MoodGroup.UPBEAT, MoodGroup.MELANCHOLY, MoodGroup.INTENSE],
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
