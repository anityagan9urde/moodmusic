"""Map Last.fm tags to mood groups."""
from __future__ import annotations

import re

from moodmusic.mood.groups import MoodGroup

MIN_SCORE = 30

# Mood words only; pure genres (rock, pop, indie...) are deliberately excluded.
TAG_KEYWORDS: dict[MoodGroup, list[str]] = {
    MoodGroup.UPBEAT: [
        "happy", "feel good", "feelgood", "upbeat", "party", "dance", "cheerful",
        "uplifting", "fun", "joyful", "summer", "danceable", "good vibes",
    ],
    MoodGroup.CHILL: [
        "chill", "chillout", "chill out", "relaxing", "relax", "mellow", "peaceful",
        "acoustic", "calm", "laid back", "soothing", "easy listening", "smooth",
    ],
    MoodGroup.MELANCHOLY: [
        "sad", "melancholy", "melancholic", "heartbreak", "rainy day", "depressing",
        "heartache", "lonely", "breakup", "sorrow", "tearjerker",
    ],
    MoodGroup.INTENSE: [
        "aggressive", "angry", "heavy", "energetic", "rock out", "intense", "powerful",
        "fierce", "adrenaline", "hard", "brutal", "workout",
    ],
    MoodGroup.FOCUS: [
        "instrumental", "ambient", "lo fi", "lofi", "study", "focus", "concentration",
        "background", "study music", "work music",
    ],
}

_SEP = re.compile(r"[-_\s]+")


def normalise(tag: str) -> str:
    return _SEP.sub(" ", tag.strip().lower()).strip()


_LOOKUP: dict[str, MoodGroup] = {
    normalise(kw): group for group, kws in TAG_KEYWORDS.items() for kw in kws
}


def score_tags(tags: list[tuple[str, int]]) -> tuple[MoodGroup | None, list[str]]:
    """Sum tag weights per group. Returns (best group or None, matched tags)."""
    scores: dict[MoodGroup, int] = {}
    matched: list[str] = []
    for name, weight in tags:
        n = normalise(name)
        group = _LOOKUP.get(n)
        if group is None:
            continue
        scores[group] = scores.get(group, 0) + int(weight)
        matched.append(n)
    if not scores:
        return None, []
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < MIN_SCORE or (len(ranked) > 1 and ranked[0] == ranked[1]):
        return None, matched
    best = max(scores, key=scores.__getitem__)
    return best, matched
