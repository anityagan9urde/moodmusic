"""Song groups (stored in the library DB) and their fallback order."""
from __future__ import annotations

from enum import Enum


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


def nearest_groups(g: MoodGroup) -> list[MoodGroup]:
    """Fallback order of other groups, closest first; never includes UNSORTED."""
    if g == MoodGroup.UNSORTED:
        return [MoodGroup.FOCUS, *_NEAREST[MoodGroup.FOCUS]]
    return list(_NEAREST[g])
