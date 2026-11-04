"""The face states the app infers (what you're doing / feeling), not song groups."""
from __future__ import annotations

from enum import Enum


class FaceState(str, Enum):
    FOCUSED = "focused"
    DEEP_THOUGHT = "deep_thought"
    LOVE = "love"
    TIRED = "tired"
    SLEEPY = "sleepy"
    STRESSED = "stressed"
    BORED = "bored"
    HAPPY = "happy"
    EXCITED = "excited"
    SAD = "sad"

    @property
    def label(self) -> str:
        return _LABEL[self]

    @property
    def emoji(self) -> str:
        return _EMOJI[self]


_LABEL = {
    FaceState.FOCUSED: "Focused", FaceState.DEEP_THOUGHT: "Deep in thought",
    FaceState.LOVE: "Love / shy", FaceState.TIRED: "Tired", FaceState.SLEEPY: "Sleepy",
    FaceState.STRESSED: "Stressed", FaceState.BORED: "Bored", FaceState.HAPPY: "Happy",
    FaceState.EXCITED: "Excited", FaceState.SAD: "Sad",
}
_EMOJI = {
    FaceState.FOCUSED: "🧠", FaceState.DEEP_THOUGHT: "🤔", FaceState.LOVE: "🥰",
    FaceState.TIRED: "🥱", FaceState.SLEEPY: "😴", FaceState.STRESSED: "😣",
    FaceState.BORED: "😐", FaceState.HAPPY: "😊", FaceState.EXCITED: "🤩", FaceState.SAD: "😢",
}

FAST_STATES = {FaceState.FOCUSED, FaceState.DEEP_THOUGHT, FaceState.LOVE,
               FaceState.HAPPY, FaceState.EXCITED, FaceState.SAD}
SLOW_STATES = {FaceState.TIRED, FaceState.SLEEPY, FaceState.STRESSED, FaceState.BORED}
# Slow states need sustained evidence over this window before they can be decided.
EVIDENCE_WINDOW_S = {FaceState.TIRED: 240, FaceState.BORED: 240,
                     FaceState.SLEEPY: 90, FaceState.STRESSED: 90}
