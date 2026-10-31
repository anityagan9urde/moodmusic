"""Pick a song for a target mood group, avoiding recent repeats."""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

from moodmusic.mood.groups import MoodGroup, nearest_groups
from moodmusic.mood.smoother import MoodState
from moodmusic.music.library import Song, SongLibrary

_MOOD_WORDS = {
    MoodGroup.UPBEAT: "upbeat and positive",
    MoodGroup.CHILL: "calm and positive",
    MoodGroup.MELANCHOLY: "low",
    MoodGroup.INTENSE: "tense",
    MoodGroup.FOCUS: "focused",
}


@dataclass
class Pick:
    song: Song
    group: MoodGroup
    reason: str
    fell_back_from: MoodGroup | None


class SongSelector:
    def __init__(self, library: SongLibrary, rng: random.Random):
        self.library = library
        self._rng = rng
        self._recent: dict[MoodGroup, deque[str]] = {}

    def mark_played(self, uri: str) -> None:
        song = self.library.get(uri)
        if song is None:
            return
        dq = self._recent.setdefault(song.group, deque())
        if uri in dq:
            dq.remove(uri)
        dq.append(uri)

    def pick(self, target: MoodGroup, mood: MoodState) -> Pick | None:
        for group in [target, *nearest_groups(target)]:
            songs = self.library.songs(group)
            if not songs:
                continue
            song = self._choose(group, songs)
            fell = target if group != target else None
            return Pick(song, group, self._reason(song, group, mood, fell), fell)
        return None

    def _choose(self, group: MoodGroup, songs: list[Song]) -> Song:
        size = max(1, int(0.8 * len(songs)))
        dq = self._recent.setdefault(group, deque())
        while len(dq) > size:
            dq.popleft()
        recent = set(dq)
        fresh = [s for s in songs if s.uri not in recent]
        if fresh:
            return self._rng.choice(fresh)
        by_uri = {s.uri: s for s in songs}
        for uri in dq:  # oldest first
            if uri in by_uri:
                return by_uri[uri]
        return self._rng.choice(songs)

    def _reason(self, song: Song, group: MoodGroup, mood: MoodState,
                fell_back_from: MoodGroup | None) -> str:
        words = _MOOD_WORDS.get(mood.group, mood.group.label.lower())
        text = f"{group.label}: you look {words}"
        if song.source == "artist":
            text += "; sorted by artist style"
        elif song.source == "user":
            text += "; you filed it here"
        elif song.tags:
            text += "; tagged " + ", ".join(song.tags[:2])
        if fell_back_from is not None:
            text += f" (no {fell_back_from.label} songs yet)"
        return text
