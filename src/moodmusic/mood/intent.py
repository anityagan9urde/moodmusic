"""What music each face state calls for (user decisions in the mood-states spec)."""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from moodmusic.mood.groups import MoodGroup as G
from moodmusic.mood.states import FaceState as F

NIGHT_START_HOUR, NIGHT_END_HOUR = 21, 6


class Mode(str, Enum):
    MATCH = "match"
    LIFT = "lift"


@dataclass(frozen=True)
class Intent:
    groups: list[G]
    fresh: bool = False
    lifting: bool = False
    note: str = ""


_LIFT_TIRED = [[G.ROMANTIC, G.CHILL], [G.CHILL, G.UPBEAT], [G.UPBEAT]]
_LIFT_CALM = [[G.CHILL], [G.CHILL, G.UPBEAT], [G.UPBEAT]]
_WAKE = [[G.UPBEAT], [G.PARTY]]
_MATCH = {
    F.FOCUSED: [G.FOCUS], F.DEEP_THOUGHT: [G.PROFOUND], F.LOVE: [G.ROMANTIC],
    F.HAPPY: [G.UPBEAT], F.EXCITED: [G.PARTY, G.INTENSE],
}


def is_night(hour: int) -> bool:
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def _step(steps: list[list[G]], n: int) -> list[G]:
    return list(steps[min(max(n, 0), len(steps) - 1)])


def intent_for(state: F, mode: Mode, step: int, hour: int, rng: random.Random) -> Intent:
    """Music for a state. `step` counts songs into a lift; `hour` is local time (0-23)."""
    if state in _MATCH:
        return Intent(list(_MATCH[state]))
    if state == F.TIRED:  # user: always lift when tired, even in Match mode
        return Intent(_step(_LIFT_TIRED, step), lifting=True, note="lifting you up")
    if state == F.STRESSED:  # user: always lift when stressed
        return Intent(_step(_LIFT_CALM, step), lifting=True, note="lifting you up")
    if state == F.BORED:
        return Intent([G.UPBEAT, G.PARTY, G.INTENSE], fresh=True, lifting=True,
                      note="something fresh")
    if state == F.SLEEPY:
        if is_night(hour):
            return Intent([G.CHILL, G.PROFOUND], note="winding down")
        return Intent(_step(_WAKE, step), lifting=True, note="waking you up")
    # SAD follows the Match/Lift toggle.
    if mode == Mode.LIFT:
        return Intent(_step(_LIFT_CALM, step), lifting=True, note="lifting you up")
    return Intent([G.MELANCHOLY])
